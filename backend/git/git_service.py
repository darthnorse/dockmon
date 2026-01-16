"""
Git operations service for git-backed stacks (v2.4.0+).

Uses native git CLI commands via subprocess for simplicity and full feature support.
All operations are async to avoid blocking the event loop.

Security:
    - SSH keys written to temp files with unique names and 0600 permissions
    - SSH keys cleaned up after each operation via try/finally
    - Error messages sanitized to remove credentials from URLs (HTTPS and SSH)
    - Path traversal prevented via resolve().relative_to() validation
    - Symlinks rejected in read_file() to prevent TOCTOU attacks

SSH Host Key Verification:
    StrictHostKeyChecking is disabled (set to 'no') for automated operation.
    This is a deliberate tradeoff:

    - Without this, initial git clone would fail because the host key is unknown
    - Users would need to manually add host keys before using git features
    - In a containerized environment, known_hosts is ephemeral anyway

    RISK: This makes the system vulnerable to man-in-the-middle attacks where
    an attacker could intercept git operations and inject malicious code.

    MITIGATIONS:
    - Use HTTPS with token auth instead of SSH when possible (more secure)
    - Git repositories should use signed commits for integrity verification
    - Production deployments should use private networks or VPNs

    FUTURE IMPROVEMENT: Consider StrictHostKeyChecking=accept-new which accepts
    new host keys but rejects changed keys (detects MITM after first connection).
"""
import asyncio
import errno
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, TYPE_CHECKING
from urllib.parse import urlparse, urlunparse, quote

from config.paths import DATA_DIR

if TYPE_CHECKING:
    from database import GitCredential, GitRepository

logger = logging.getLogger(__name__)

# Public API
__all__ = [
    'GitService',
    'GitNotAvailableError',
    'SyncResult',
    'get_git_service',
    'GIT_REPOS_DIR',
]

# Default directory for cloned repositories
GIT_REPOS_DIR = Path(os.environ.get('GIT_REPOS_DIR', os.path.join(DATA_DIR, 'git-repos')))


@dataclass
class SyncResult:
    """Result of a git sync operation (clone or pull)."""
    success: bool
    updated: bool  # True if new commits were pulled
    commit: Optional[str]
    error: Optional[str] = None


class GitNotAvailableError(RuntimeError):
    """Raised when git is not installed or not accessible."""
    pass


class GitService:
    """
    Git operations using native CLI.

    All methods are async to avoid blocking the event loop on slow storage (NFS, etc.).
    SSH keys are written to temp files and cleaned up after each operation.
    """

    def __init__(self, repos_dir: Optional[str] = None):
        """
        Initialize GitService.

        Args:
            repos_dir: Directory to store cloned repositories.
                      Defaults to /app/data/git-repos/

        Raises:
            GitNotAvailableError: If git is not installed
        """
        self.repos_dir = Path(repos_dir) if repos_dir else GIT_REPOS_DIR
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self._verify_git_available()

    def _verify_git_available(self) -> None:
        """
        Verify git is installed and accessible.

        Raises:
            GitNotAvailableError: If git command fails
        """
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise GitNotAvailableError("Git command failed")
            logger.info(f"Git available: {result.stdout.strip()}")
        except FileNotFoundError:
            raise GitNotAvailableError(
                "Git not found. Install git in the container: apk add git"
            )
        except subprocess.TimeoutExpired:
            raise GitNotAvailableError("Git command timed out")

    def get_repo_path(self, repo_id: int) -> Path:
        """
        Get local filesystem path for a repository.

        Args:
            repo_id: Repository database ID

        Returns:
            Path to cloned repository directory
        """
        return self.repos_dir / f"repo-{repo_id}"

    async def clone(
        self,
        repo: 'GitRepository',
        branch: Optional[str] = None
    ) -> SyncResult:
        """
        Clone a repository (shallow clone to save space).

        If repository already exists locally, performs a pull instead.

        Args:
            repo: GitRepository instance with URL and credentials
            branch: Branch to clone (defaults to repo.branch)

        Returns:
            SyncResult with success status, commit hash, and any errors
        """
        repo_path = self.get_repo_path(repo.id)
        target_branch = branch or repo.branch

        # Validate branch is specified
        if not target_branch:
            return SyncResult(
                success=False,
                updated=False,
                commit=None,
                error="No branch specified for clone"
            )

        if repo_path.exists():
            return await self.pull(repo, branch)

        url = self._build_auth_url(repo.url, repo.credential)
        env, key_path = self._build_git_env(repo.credential)

        try:
            result = await self._run_git(
                ['clone', '--depth=1', '--branch', target_branch, url, str(repo_path)],
                cwd=self.repos_dir,
                env=env,
                timeout=600  # 10 minutes for initial clone of large repos
            )

            if result.returncode != 0:
                error = self._sanitize_error(result.stderr) if result.stderr else "Clone failed"
                return SyncResult(success=False, updated=False, commit=None, error=error)

            commit = await self._get_head_commit(repo_path, env)
            logger.info(f"Cloned repository {repo.id} ({repo.name}) at {commit}")
            return SyncResult(success=True, updated=True, commit=commit)
        finally:
            self._cleanup_ssh_key(key_path)

    async def pull(
        self,
        repo: 'GitRepository',
        branch: Optional[str] = None
    ) -> SyncResult:
        """
        Pull latest changes from remote.

        Uses fetch + reset to handle force pushes gracefully.

        Args:
            repo: GitRepository instance
            branch: Branch to pull (defaults to repo.branch)

        Returns:
            SyncResult with success status and whether commits were pulled
        """
        repo_path = self.get_repo_path(repo.id)
        target_branch = branch or repo.branch

        # Validate branch is specified
        if not target_branch:
            return SyncResult(
                success=False,
                updated=False,
                commit=None,
                error="No branch specified for pull"
            )

        env, key_path = self._build_git_env(repo.credential)

        if not repo_path.exists():
            return await self.clone(repo, branch)

        try:
            # Get current commit before pull
            old_commit = await self._get_head_commit(repo_path, env)

            # Fetch and reset to remote (handles force pushes)
            fetch_result = await self._run_git(
                ['fetch', 'origin', target_branch],
                cwd=repo_path,
                env=env
            )
            if fetch_result.returncode != 0:
                error = self._sanitize_error(fetch_result.stderr) if fetch_result.stderr else "Fetch failed"
                return SyncResult(success=False, updated=False, commit=old_commit, error=error)

            reset_result = await self._run_git(
                ['reset', '--hard', f'origin/{target_branch}'],
                cwd=repo_path,
                env=env
            )
            if reset_result.returncode != 0:
                error = self._sanitize_error(reset_result.stderr) if reset_result.stderr else "Reset failed"
                return SyncResult(success=False, updated=False, commit=old_commit, error=error)

            new_commit = await self._get_head_commit(repo_path, env)
            updated = old_commit != new_commit

            if updated:
                logger.info(f"Pulled repository {repo.id} ({repo.name}): {old_commit} -> {new_commit}")
            else:
                logger.debug(f"Repository {repo.id} ({repo.name}) unchanged at {new_commit}")

            return SyncResult(success=True, updated=updated, commit=new_commit)
        finally:
            self._cleanup_ssh_key(key_path)

    async def test_connection(
        self,
        url: str,
        branch: str,
        credential: Optional['GitCredential'] = None
    ) -> Tuple[bool, str]:
        """
        Test if repository is accessible without cloning.

        Uses git ls-remote to check connectivity.

        Args:
            url: Repository URL
            branch: Branch to check
            credential: Optional credentials for authentication

        Returns:
            Tuple of (success, message)
        """
        auth_url = self._build_auth_url(url, credential)
        env, key_path = self._build_git_env(credential)

        try:
            result = await self._run_git(
                ['ls-remote', '--heads', auth_url, branch],
                cwd=self.repos_dir,
                env=env,
                timeout=30
            )

            if result.returncode == 0:
                return True, "Connection successful"

            error_msg = self._sanitize_error(result.stderr) if result.stderr else "Connection failed"
            return False, error_msg
        finally:
            self._cleanup_ssh_key(key_path)

    def read_file(self, repo: 'GitRepository', file_path: str) -> Optional[str]:
        """
        Read a file from the cloned repository.

        Security:
            - Validates path doesn't escape repo BEFORE any file operations
            - Uses O_NOFOLLOW to atomically reject symlinks (prevents TOCTOU)

        Args:
            repo: GitRepository instance
            file_path: Relative path within the repository

        Returns:
            File contents, or None if not found or path traversal detected
        """
        repo_path = self.get_repo_path(repo.id)
        full_path = repo_path / file_path

        # Security: Validate path doesn't escape repo BEFORE any file operations
        # This prevents information leaks from exists() following symlinks
        try:
            resolved = full_path.resolve()
            resolved.relative_to(repo_path.resolve())
        except ValueError:
            logger.warning(f"Path traversal attempt blocked: {file_path}")
            return None

        # Use O_NOFOLLOW to atomically reject symlinks during open
        # This eliminates TOCTOU race condition between check and read
        try:
            fd = os.open(str(full_path), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as e:
            # ELOOP or EMLINK indicates symlink with O_NOFOLLOW
            if e.errno in (errno.ELOOP, errno.EMLINK):
                logger.warning(f"Symlink blocked in repo read: {file_path}")
            return None

        try:
            with os.fdopen(fd, 'r') as f:
                return f.read()
        except UnicodeDecodeError:
            logger.warning(f"Binary file cannot be read as text: {file_path}")
            return None

    def _is_path_within_repo(self, path: Path, repo_path: Path) -> bool:
        """
        Check if a path is within the repository directory.

        Args:
            path: Path to check
            repo_path: Repository root path

        Returns:
            True if path is within repo, False otherwise
        """
        try:
            path.resolve().relative_to(repo_path.resolve())
            return True
        except ValueError:
            return False

    def list_compose_files(self, repo: 'GitRepository') -> List[str]:
        """
        List compose files (*.yml and *.yaml) in repository.

        Useful for UI file picker when linking a stack to git.

        Args:
            repo: GitRepository instance

        Returns:
            Sorted list of relative paths to compose files
        """
        repo_path = self.get_repo_path(repo.id)
        if not repo_path.exists():
            return []

        files = []
        for pattern in ["*.yml", "*.yaml"]:
            files.extend(
                str(p.relative_to(repo_path))
                for p in repo_path.rglob(pattern)
                if p.is_file() and self._is_path_within_repo(p, repo_path)
            )
        return sorted(set(files))  # Dedupe and sort

    def list_files(self, repo: 'GitRepository', pattern: str) -> List[str]:
        """
        List files in repository matching a specific pattern.

        Security:
            - Rejects patterns containing path traversal sequences
            - Validates all returned paths are within the repository

        Args:
            repo: GitRepository instance
            pattern: Glob pattern to match (e.g., "*.env", "**/.env")

        Returns:
            List of relative paths matching the pattern, or empty list if
            pattern is invalid or no matches found
        """
        # Reject patterns with path traversal sequences
        if '..' in pattern:
            logger.warning(f"Path traversal in glob pattern rejected: {pattern}")
            return []

        repo_path = self.get_repo_path(repo.id)
        if not repo_path.exists():
            return []

        # Filter results to ensure all paths are within repo
        return [
            str(p.relative_to(repo_path))
            for p in repo_path.rglob(pattern)
            if p.is_file() and self._is_path_within_repo(p, repo_path)
        ]

    def cleanup_repo(self, repo_id: int) -> None:
        """
        Delete cloned repository from disk.

        Called when a GitRepository is deleted from the database.

        Args:
            repo_id: Repository database ID
        """
        repo_path = self.get_repo_path(repo_id)
        if repo_path.exists():
            shutil.rmtree(repo_path)
            logger.info(f"Deleted cloned repository: {repo_path}")

    def repo_exists(self, repo_id: int) -> bool:
        """
        Check if a repository is cloned locally.

        Args:
            repo_id: Repository database ID

        Returns:
            True if the repository directory exists
        """
        return self.get_repo_path(repo_id).exists()

    async def _run_git(
        self,
        args: List[str],
        cwd: Path,
        env: Optional[dict] = None,
        timeout: int = 300
    ) -> subprocess.CompletedProcess:
        """
        Run git command asynchronously.

        Args:
            args: Git command arguments (without 'git' prefix)
            cwd: Working directory
            env: Additional environment variables
            timeout: Command timeout in seconds (default 5 minutes)

        Returns:
            CompletedProcess with stdout, stderr, and returncode
        """
        full_env = {
            **os.environ,
            'GIT_TERMINAL_PROMPT': '0',  # Disable interactive prompts
            'GIT_SSH_COMMAND': 'ssh -o BatchMode=yes -o StrictHostKeyChecking=no',
            **(env or {})
        }

        return await asyncio.to_thread(
            subprocess.run,
            ['git'] + args,
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    async def _get_head_commit(self, repo_path: Path, env: dict) -> Optional[str]:
        """
        Get current HEAD commit hash.

        Args:
            repo_path: Path to repository
            env: Environment variables for git

        Returns:
            Full commit SHA, or None on error
        """
        result = await self._run_git(['rev-parse', 'HEAD'], cwd=repo_path, env=env)
        return result.stdout.strip() if result.returncode == 0 else None

    def _build_auth_url(
        self,
        url: str,
        credential: Optional['GitCredential']
    ) -> str:
        """
        Build URL with embedded credentials for HTTPS auth.

        Args:
            url: Repository URL
            credential: Optional credential with username/password

        Returns:
            URL with embedded credentials (for HTTPS) or unchanged (for SSH/none)
        """
        if not credential or credential.auth_type != 'https':
            return url

        if credential.username and credential.password:
            # https://user:pass@github.com/org/repo.git
            parsed = urlparse(url)
            # Validate URL has a hostname before embedding credentials
            if not parsed.hostname:
                logger.warning(f"Malformed URL (no hostname), cannot add credentials: {url}")
                return url
            # URL-encode password to handle special characters
            encoded_password = quote(credential.password, safe='')
            netloc = f"{credential.username}:{encoded_password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))

        return url

    def _get_ssh_key_dir(self) -> Path:
        """
        Get directory for temporary SSH key files.

        Prefers /dev/shm (RAM-backed tmpfs) to avoid writing keys to disk.
        Falls back to repos_dir if /dev/shm is not available or writable.

        Returns:
            Path to directory for SSH key temp files
        """
        shm_path = Path('/dev/shm')
        if shm_path.exists() and shm_path.is_dir():
            try:
                # Verify we can write to /dev/shm
                test_file = shm_path / f".dockmon-test-{uuid.uuid4().hex[:8]}"
                test_file.touch()
                test_file.unlink()
                return shm_path
            except (OSError, IOError):
                pass
        return self.repos_dir

    def _build_git_env(
        self,
        credential: Optional['GitCredential']
    ) -> Tuple[dict, Optional[Path]]:
        """
        Build environment variables for git authentication.

        For SSH auth, writes the private key to a temp file with restrictive permissions.
        Prefers /dev/shm (RAM-backed) to avoid persisting keys to disk.

        Args:
            credential: Optional credential with SSH key

        Returns:
            Tuple of (env_dict, key_path) where key_path is the temp SSH key file
            that must be cleaned up after the operation.
        """
        if not credential or credential.auth_type != 'ssh':
            return {}, None

        if credential.ssh_private_key:
            # Write temp SSH key file with unique name to prevent race conditions
            # when multiple operations use the same credential concurrently
            # Use /dev/shm (RAM) if available to avoid disk persistence
            key_dir = self._get_ssh_key_dir()
            key_path = key_dir / f".ssh-key-{credential.id}-{uuid.uuid4().hex[:8]}"
            try:
                key_path.write_text(credential.ssh_private_key)
                key_path.chmod(0o600)
            except Exception:
                # Clean up orphaned key file on failure
                if key_path.exists():
                    key_path.unlink()
                raise

            ssh_cmd = f'ssh -i "{key_path}" -o BatchMode=yes -o StrictHostKeyChecking=no -o IdentitiesOnly=yes'
            return {'GIT_SSH_COMMAND': ssh_cmd}, key_path

        return {}, None

    def _cleanup_ssh_key(self, key_path: Optional[Path]) -> None:
        """
        Remove temporary SSH key file.

        Args:
            key_path: Path to SSH key file, or None if no cleanup needed
        """
        if key_path and key_path.exists():
            key_path.unlink()

    def _sanitize_error(self, error: str) -> str:
        """
        Remove credentials and sensitive paths from error messages.

        Git errors may contain:
        - HTTPS URLs with embedded credentials (user:pass@host)
        - SSH URLs with usernames (user@host)
        - Paths to temporary SSH key files

        Args:
            error: Error message that may contain sensitive information

        Returns:
            Sanitized error message with credentials and key paths removed
        """
        result = error

        # Pattern 1: HTTPS URLs with credentials - https://user:pass@host/path
        # Uses greedy match to handle passwords containing @ characters
        # Lookahead ensures we only strip up to the last @ before the hostname
        https_pattern = r'(https?://)[^\s]+@(?=[a-zA-Z0-9])'
        result = re.sub(https_pattern, r'\1', result)

        # Pattern 2: SSH URLs with username - ssh://user@host or git@host:path
        # Remove username from ssh:// URLs
        ssh_url_pattern = r'(ssh://)([^@]+)@([^\s]+)'
        result = re.sub(ssh_url_pattern, r'\1\3', result)

        # Pattern 3: git@ style URLs - git@github.com:org/repo
        # These don't expose passwords but may reveal usernames
        git_at_pattern = r'([a-zA-Z0-9_-]+)@([a-zA-Z0-9.-]+):([^\s]+)'
        result = re.sub(git_at_pattern, r'***@\2:\3', result)

        # Pattern 4: Temporary SSH key file paths - /path/.ssh-key-N-xxxxxxxx
        # These reveal the credential ID and should be hidden
        ssh_key_path_pattern = r'[^\s]*\.ssh-key-\d+-[a-f0-9]+[^\s]*'
        result = re.sub(ssh_key_path_pattern, '[SSH_KEY_FILE]', result)

        return result


# Singleton instance with thread-safe initialization
_git_service: Optional[GitService] = None
_git_service_lock = threading.Lock()


def get_git_service() -> GitService:
    """
    Get or create the singleton GitService instance.

    Thread-safe using double-checked locking pattern.

    Returns:
        GitService instance

    Raises:
        GitNotAvailableError: If git is not installed
    """
    global _git_service

    # Fast path: instance already exists
    if _git_service is not None:
        return _git_service

    # Slow path: acquire lock and create instance
    with _git_service_lock:
        # Double-check: another thread might have created it while we waited
        if _git_service is None:
            _git_service = GitService()
        return _git_service
