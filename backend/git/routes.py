"""
Git API routes for DockMon v2.4.0+

Provides REST endpoints for git-backed stack management:
- Git credentials CRUD (admin-only for write operations)
- Git repositories CRUD with sync status
- Test connection, manual sync, list files

Security:
    - All write operations require admin scope
    - Credential responses never include secrets (only has_* flags)
    - URLs validated to prevent injection
    - Security audit logging for privileged actions
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, NamedTuple, Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_scope
from database import DatabaseManager, GitCredential, GitRepository
from deployment.stack_storage import get_stacks_linked_to_repo, get_all_linked_stack_counts
from git.git_service import get_git_service, GitNotAvailableError
from models.git_models import (
    GitCredentialCreate,
    GitCredentialUpdate,
    GitCredentialResponse,
    GitRepositoryCreate,
    GitRepositoryUpdate,
    GitRepositoryResponse,
    GitTestConnectionRequest,
    GitTestConnectionResponse,
    GitSyncResponse,
    GitFileListResponse,
)
from security.audit import security_audit
from security.rate_limiting import rate_limit_default

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/git", tags=["git"])

# Module-level database manager reference
_db_manager: Optional[DatabaseManager] = None

# Timeout for stuck sync detection (10 minutes)
SYNC_STUCK_TIMEOUT_MINUTES = 10


def set_database_manager(db: DatabaseManager) -> None:
    """Set the database manager reference."""
    global _db_manager
    _db_manager = db


def get_db() -> DatabaseManager:
    """Get database manager, raising error if not initialized."""
    if _db_manager is None:
        raise RuntimeError("Database manager not initialized for git routes")
    return _db_manager


# =============================================================================
# Helper Functions
# =============================================================================


def _log_audit(request: Request, action: str, target: str, success: bool = True) -> None:
    """Log privileged action with standard fields."""
    security_audit.log_privileged_action(
        client_ip=request.client.host if request.client else "unknown",
        action=action,
        target=target,
        success=success,
        user_agent=request.headers.get('user-agent', 'unknown'),
    )


def _get_credential_or_404(session: Session, credential_id: int) -> GitCredential:
    """Get credential by ID or raise 404."""
    credential = session.query(GitCredential).filter(GitCredential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


def _get_repo_or_404(session: Session, repo_id: int) -> GitRepository:
    """Get repository by ID or raise 404."""
    repo = session.query(GitRepository).filter(GitRepository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _get_git_service_or_503():
    """Get git service or raise 503 if unavailable."""
    try:
        return get_git_service()
    except GitNotAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


class TempCredential(NamedTuple):
    """Temporary credential for test_connection without database record."""
    id: int
    auth_type: str
    username: Optional[str]
    password: Optional[str]
    ssh_private_key: Optional[str]


# =============================================================================
# Git Credentials Endpoints
# =============================================================================


@router.get("/credentials", response_model=List[GitCredentialResponse])
async def list_credentials(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """List all git credentials (sanitized - no secrets exposed)."""
    db = get_db()
    session = db.get_session()
    try:
        credentials = (
            session.query(GitCredential)
            .order_by(GitCredential.name)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [GitCredentialResponse.from_db(c) for c in credentials]
    finally:
        session.close()


@router.post(
    "/credentials",
    response_model=GitCredentialResponse,
    status_code=201,
    dependencies=[Depends(require_scope("admin"))],
)
async def create_credential(
    data: GitCredentialCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Create a new git credential. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        # Validate auth_type matches provided credentials
        if data.auth_type == 'https':
            if not data.username:
                raise HTTPException(status_code=400, detail="HTTPS auth requires username")
            if not data.password:
                raise HTTPException(status_code=400, detail="HTTPS auth requires password or token")
        if data.auth_type == 'ssh' and not data.ssh_private_key:
            raise HTTPException(status_code=400, detail="SSH auth requires ssh_private_key")

        credential = GitCredential(
            name=data.name,
            auth_type=data.auth_type,
            username=data.username,
        )
        if data.password:
            credential.password = data.password
        if data.ssh_private_key:
            credential.ssh_private_key = data.ssh_private_key

        session.add(credential)
        session.commit()
        session.refresh(credential)

        _log_audit(request, "CREATE_GIT_CREDENTIAL", data.name)
        logger.info(f"Created git credential: {data.name}")
        return GitCredentialResponse.from_db(credential)

    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"Credential with name '{data.name}' already exists")
    finally:
        session.close()


@router.get("/credentials/{credential_id}", response_model=GitCredentialResponse)
async def get_credential(
    credential_id: int,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Get a git credential by ID (sanitized - no secrets exposed)."""
    db = get_db()
    session = db.get_session()
    try:
        credential = _get_credential_or_404(session, credential_id)
        return GitCredentialResponse.from_db(credential)
    finally:
        session.close()


@router.put(
    "/credentials/{credential_id}",
    response_model=GitCredentialResponse,
    dependencies=[Depends(require_scope("admin"))],
)
async def update_credential(
    credential_id: int,
    data: GitCredentialUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Update a git credential. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        credential = _get_credential_or_404(session, credential_id)

        if data.name is not None:
            credential.name = data.name
        if data.auth_type is not None:
            credential.auth_type = data.auth_type
        if data.username is not None:
            credential.username = data.username

        if data.clear_password:
            credential.password = None
        elif data.password is not None:
            credential.password = data.password

        if data.clear_ssh_key:
            credential.ssh_private_key = None
        elif data.ssh_private_key is not None:
            credential.ssh_private_key = data.ssh_private_key

        session.commit()
        session.refresh(credential)

        _log_audit(request, "UPDATE_GIT_CREDENTIAL", credential.name)
        logger.info(f"Updated git credential: {credential.name}")
        return GitCredentialResponse.from_db(credential)

    except IntegrityError:
        session.rollback()
        conflict_name = data.name if data.name is not None else credential.name
        raise HTTPException(status_code=409, detail=f"Credential with name '{conflict_name}' already exists")
    finally:
        session.close()


@router.delete(
    "/credentials/{credential_id}",
    status_code=204,
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_credential(
    credential_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Delete a git credential. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        credential = _get_credential_or_404(session, credential_id)
        credential_name = credential.name

        session.delete(credential)
        session.commit()

        _log_audit(request, "DELETE_GIT_CREDENTIAL", credential_name)
        logger.info(f"Deleted git credential: {credential_name}")
        return None
    finally:
        session.close()


# =============================================================================
# Git Repositories Endpoints
# =============================================================================


@router.get("/repositories", response_model=List[GitRepositoryResponse])
async def list_repositories(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """List all git repositories with sync status and linked stacks count."""
    db = get_db()
    session = db.get_session()
    try:
        repos = (
            session.query(GitRepository)
            .order_by(GitRepository.name)
            .offset(offset)
            .limit(limit)
            .all()
        )
        linked_counts = await get_all_linked_stack_counts()
        return [GitRepositoryResponse.from_db(repo, linked_counts.get(repo.id, 0)) for repo in repos]
    finally:
        session.close()


@router.post(
    "/repositories",
    response_model=GitRepositoryResponse,
    status_code=201,
    dependencies=[Depends(require_scope("admin"))],
)
async def create_repository(
    data: GitRepositoryCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Create a new git repository. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        if data.credential_id is not None:
            cred = session.query(GitCredential).filter(GitCredential.id == data.credential_id).first()
            if not cred:
                raise HTTPException(status_code=400, detail="Credential not found")

        repo = GitRepository(
            name=data.name,
            url=data.url,
            branch=data.branch,
            credential_id=data.credential_id,
            auto_sync_enabled=data.auto_sync_enabled,
            auto_sync_cron=data.auto_sync_cron,
        )

        session.add(repo)
        session.commit()
        session.refresh(repo)

        _log_audit(request, "CREATE_GIT_REPOSITORY", f"{data.name} ({data.url})")
        logger.info(f"Created git repository: {data.name}")
        return GitRepositoryResponse.from_db(repo, 0)

    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"Repository with name '{data.name}' already exists")
    finally:
        session.close()


@router.get("/repositories/{repo_id}", response_model=GitRepositoryResponse)
async def get_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Get a git repository by ID."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)
        linked_stacks = await get_stacks_linked_to_repo(repo.id)
        return GitRepositoryResponse.from_db(repo, len(linked_stacks))
    finally:
        session.close()


@router.put(
    "/repositories/{repo_id}",
    response_model=GitRepositoryResponse,
    dependencies=[Depends(require_scope("admin"))],
)
async def update_repository(
    repo_id: int,
    data: GitRepositoryUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Update a git repository. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)

        if data.name is not None:
            repo.name = data.name
        if data.url is not None:
            repo.url = data.url
        if data.branch is not None:
            repo.branch = data.branch
        if data.auto_sync_enabled is not None:
            repo.auto_sync_enabled = data.auto_sync_enabled
        if data.auto_sync_cron is not None:
            repo.auto_sync_cron = data.auto_sync_cron

        if data.clear_credential:
            repo.credential_id = None
        elif data.credential_id is not None:
            cred = session.query(GitCredential).filter(GitCredential.id == data.credential_id).first()
            if not cred:
                raise HTTPException(status_code=400, detail="Credential not found")
            repo.credential_id = data.credential_id

        session.commit()
        session.refresh(repo)

        _log_audit(request, "UPDATE_GIT_REPOSITORY", repo.name)
        linked_stacks = await get_stacks_linked_to_repo(repo.id)
        logger.info(f"Updated git repository: {repo.name}")
        return GitRepositoryResponse.from_db(repo, len(linked_stacks))

    except IntegrityError:
        session.rollback()
        conflict_name = data.name if data.name is not None else repo.name
        raise HTTPException(status_code=409, detail=f"Repository with name '{conflict_name}' already exists")
    finally:
        session.close()


@router.delete(
    "/repositories/{repo_id}",
    status_code=204,
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_repository(
    repo_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Delete a git repository. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)
        repo_name = repo.name
        repo_id_for_cleanup = repo.id

        session.delete(repo)
        session.commit()

        # Clean up cloned repository from disk (non-critical)
        try:
            git_service = get_git_service()
            git_service.cleanup_repo(repo_id_for_cleanup)
        except (GitNotAvailableError, Exception) as e:
            logger.warning(f"Failed to cleanup cloned repo: {e}")

        _log_audit(request, "DELETE_GIT_REPOSITORY", repo_name)
        logger.info(f"Deleted git repository: {repo_name}")
        return None
    finally:
        session.close()


# =============================================================================
# Git Operations Endpoints
# =============================================================================


@router.post(
    "/repositories/test-connection",
    response_model=GitTestConnectionResponse,
    dependencies=[Depends(require_scope("admin"))],
)
async def test_connection(
    data: GitTestConnectionRequest,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Test connection to a git repository without saving. Requires admin scope."""
    git_service = _get_git_service_or_503()

    credential = None
    if data.auth_type != 'none':
        credential = TempCredential(
            id=0,
            auth_type=data.auth_type,
            username=data.username,
            password=data.password,
            ssh_private_key=data.ssh_private_key,
        )

    success, message = await git_service.test_connection(data.url, data.branch, credential)
    return GitTestConnectionResponse(success=success, message=message)


@router.post(
    "/repositories/{repo_id}/test",
    response_model=GitTestConnectionResponse,
    dependencies=[Depends(require_scope("admin"))],
)
async def test_repository_connection(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Test connection to an existing repository. Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)
        git_service = _get_git_service_or_503()
        success, message = await git_service.test_connection(repo.url, repo.branch, repo.credential)
        return GitTestConnectionResponse(success=success, message=message)
    finally:
        session.close()


@router.post(
    "/repositories/{repo_id}/sync",
    response_model=GitSyncResponse,
    dependencies=[Depends(require_scope("admin"))],
)
async def sync_repository(
    repo_id: int,
    request: Request,
    force: bool = Query(default=False, description="Force sync even if stuck in syncing state"),
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """Manually sync a repository (clone or pull). Requires admin scope."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)

        # Concurrent protection with stuck detection
        if repo.sync_status == 'syncing':
            stuck_threshold = datetime.utcnow() - timedelta(minutes=SYNC_STUCK_TIMEOUT_MINUTES)
            is_stuck = repo.updated_at < stuck_threshold if repo.updated_at else True

            if force and is_stuck:
                logger.warning(f"Forcing sync for stuck repository {repo.name} (stuck since {repo.updated_at})")
            elif is_stuck:
                raise HTTPException(
                    status_code=409,
                    detail=f"Sync appears stuck (no progress for {SYNC_STUCK_TIMEOUT_MINUTES}+ minutes). Use force=true to override."
                )
            else:
                raise HTTPException(status_code=409, detail="Sync already in progress")

        git_service = _get_git_service_or_503()

        # Mark as syncing
        repo.sync_status = 'syncing'
        repo.sync_error = None
        session.commit()

        try:
            result = await git_service.pull(repo) if git_service.repo_exists(repo.id) else await git_service.clone(repo)

            if result.success:
                repo.sync_status = 'synced'
                repo.last_commit = result.commit
                repo.last_sync_at = datetime.utcnow()
            else:
                repo.sync_status = 'error'
                repo.sync_error = result.error

            session.commit()
            _log_audit(request, "SYNC_GIT_REPOSITORY", repo.name, result.success)

            return GitSyncResponse(
                success=result.success,
                updated=result.updated,
                commit=result.commit,
                error=result.error,
            )

        except Exception as e:
            repo.sync_status = 'error'
            repo.sync_error = str(e)
            session.commit()
            raise HTTPException(status_code=500, detail=f"Sync failed: {e}")

    finally:
        session.close()


@router.get("/repositories/{repo_id}/files", response_model=GitFileListResponse)
async def list_repository_files(
    repo_id: int,
    pattern: str = "*.yml,*.yaml",
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default,
):
    """List files in a repository matching patterns."""
    db = get_db()
    session = db.get_session()
    try:
        repo = _get_repo_or_404(session, repo_id)
        git_service = _get_git_service_or_503()

        if not git_service.repo_exists(repo.id):
            raise HTTPException(status_code=400, detail="Repository not synced. Call sync endpoint first.")

        patterns = [p.strip() for p in pattern.split(',') if p.strip()]
        for p in patterns:
            if '..' in p:
                raise HTTPException(status_code=400, detail="Pattern cannot contain path traversal sequences (..)")

        all_files = []
        for p in patterns:
            files = await asyncio.to_thread(git_service.list_files, repo, p)
            all_files.extend(files)

        files = sorted(set(all_files))
        return GitFileListResponse(files=files, total=len(files))
    finally:
        session.close()
