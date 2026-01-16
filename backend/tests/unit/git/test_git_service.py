"""
Unit tests for GitService.

Tests verify:
- Git availability check
- URL building with credentials
- SSH key handling
- Error message sanitization
- Path traversal prevention
- File listing operations

Following TDD principles: RED -> GREEN -> REFACTOR
"""

import pytest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from git.git_service import GitService, GitNotAvailableError, SyncResult


class TestGitServiceInitialization:
    """Tests for GitService initialization"""

    def test_creates_repos_directory(self, tmp_path):
        """Should create repos directory if it doesn't exist"""
        repos_dir = tmp_path / "git-repos"
        assert not repos_dir.exists()

        with patch.object(GitService, '_verify_git_available'):
            service = GitService(repos_dir=str(repos_dir))

        assert repos_dir.exists()

    def test_raises_error_when_git_not_available(self, tmp_path):
        """Should raise GitNotAvailableError when git is not installed"""
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            with pytest.raises(GitNotAvailableError, match="Git not found"):
                GitService(repos_dir=str(tmp_path))

    def test_raises_error_when_git_command_fails(self, tmp_path):
        """Should raise GitNotAvailableError when git --version fails"""
        mock_result = Mock()
        mock_result.returncode = 1

        with patch('subprocess.run', return_value=mock_result):
            with pytest.raises(GitNotAvailableError, match="Git command failed"):
                GitService(repos_dir=str(tmp_path))

    def test_accepts_git_version_output(self, tmp_path):
        """Should initialize successfully when git --version returns 0"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "git version 2.39.0"

        with patch('subprocess.run', return_value=mock_result):
            service = GitService(repos_dir=str(tmp_path))

        assert service.repos_dir == tmp_path


class TestGetRepoPath:
    """Tests for get_repo_path method"""

    def test_returns_correct_path(self, tmp_path):
        """Should return repos_dir/repo-{id}"""
        with patch.object(GitService, '_verify_git_available'):
            service = GitService(repos_dir=str(tmp_path))

        path = service.get_repo_path(123)
        assert path == tmp_path / "repo-123"

    def test_handles_different_ids(self, tmp_path):
        """Should work with various repository IDs"""
        with patch.object(GitService, '_verify_git_available'):
            service = GitService(repos_dir=str(tmp_path))

        assert service.get_repo_path(1).name == "repo-1"
        assert service.get_repo_path(999).name == "repo-999"


class TestBuildAuthUrl:
    """Tests for _build_auth_url method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_returns_unchanged_url_for_none_credential(self, service):
        """Should return original URL when no credential provided"""
        url = "https://github.com/org/repo.git"
        result = service._build_auth_url(url, None)
        assert result == url

    def test_returns_unchanged_url_for_non_https_credential(self, service):
        """Should return original URL for SSH auth type"""
        url = "git@github.com:org/repo.git"
        credential = Mock(auth_type='ssh')

        result = service._build_auth_url(url, credential)
        assert result == url

    def test_returns_unchanged_url_for_none_auth_type(self, service):
        """Should return original URL for 'none' auth type"""
        url = "https://github.com/org/repo.git"
        credential = Mock(auth_type='none')

        result = service._build_auth_url(url, credential)
        assert result == url

    def test_embeds_credentials_for_https(self, service):
        """Should embed username:password in HTTPS URL"""
        url = "https://github.com/org/repo.git"
        credential = Mock(auth_type='https', username='user', password='secret')

        result = service._build_auth_url(url, credential)
        assert result == "https://user:secret@github.com/org/repo.git"

    def test_url_encodes_special_characters_in_password(self, service):
        """Should URL-encode special characters in password"""
        url = "https://github.com/org/repo.git"
        credential = Mock(auth_type='https', username='user', password='p@ss/word#123')

        result = service._build_auth_url(url, credential)
        # @ should be %40, / should be %2F, # should be %23
        assert "p%40ss%2Fword%23123" in result

    def test_preserves_port_in_url(self, service):
        """Should preserve port number when embedding credentials"""
        url = "https://git.example.com:8443/org/repo.git"
        credential = Mock(auth_type='https', username='user', password='pass')

        result = service._build_auth_url(url, credential)
        assert ":8443" in result
        assert "user:pass@git.example.com:8443" in result


class TestBuildGitEnv:
    """Tests for _build_git_env method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_returns_empty_for_none_credential(self, service):
        """Should return empty dict when no credential provided"""
        env, key_path = service._build_git_env(None)
        assert env == {}
        assert key_path is None

    def test_returns_empty_for_non_ssh_credential(self, service):
        """Should return empty dict for HTTPS auth type"""
        credential = Mock(auth_type='https')

        env, key_path = service._build_git_env(credential)
        assert env == {}
        assert key_path is None

    def test_writes_ssh_key_to_temp_file(self, service):
        """Should write SSH private key to temp file with 0600 permissions"""
        credential = Mock(
            auth_type='ssh',
            id=1,
            ssh_private_key="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        )

        env, key_path = service._build_git_env(credential)

        try:
            assert key_path is not None
            assert key_path.exists()
            assert key_path.stat().st_mode & 0o777 == 0o600
            assert "GIT_SSH_COMMAND" in env
            assert str(key_path) in env["GIT_SSH_COMMAND"]
        finally:
            service._cleanup_ssh_key(key_path)

    def test_creates_unique_key_filename(self, service):
        """Should create unique filename for concurrent operations"""
        credential = Mock(
            auth_type='ssh',
            id=5,
            ssh_private_key="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        )

        env1, key_path1 = service._build_git_env(credential)
        env2, key_path2 = service._build_git_env(credential)

        try:
            assert key_path1 != key_path2
            assert "repo-5-" in key_path1.name or ".ssh-key-5-" in key_path1.name
        finally:
            service._cleanup_ssh_key(key_path1)
            service._cleanup_ssh_key(key_path2)


class TestCleanupSshKey:
    """Tests for _cleanup_ssh_key method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_removes_existing_key_file(self, service, tmp_path):
        """Should remove key file when it exists"""
        key_path = tmp_path / "test-key"
        key_path.write_text("test content")
        assert key_path.exists()

        service._cleanup_ssh_key(key_path)
        assert not key_path.exists()

    def test_handles_none_key_path(self, service):
        """Should handle None key_path gracefully"""
        service._cleanup_ssh_key(None)  # Should not raise

    def test_handles_nonexistent_key_path(self, service, tmp_path):
        """Should handle non-existent file gracefully"""
        key_path = tmp_path / "nonexistent-key"
        assert not key_path.exists()

        service._cleanup_ssh_key(key_path)  # Should not raise


class TestSanitizeError:
    """Tests for _sanitize_error method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_removes_https_credentials_from_error(self, service):
        """Should remove username:password from HTTPS URLs"""
        error = "fatal: unable to access 'https://user:secretpass@github.com/org/repo.git/'"
        result = service._sanitize_error(error)
        assert "secretpass" not in result
        assert "user:" not in result
        assert "github.com/org/repo.git" in result

    def test_handles_multiple_urls_in_error(self, service):
        """Should sanitize multiple URLs in one error message"""
        error = "Error: https://user1:pass1@host1.com/repo failed, tried https://user2:pass2@host2.com/repo"
        result = service._sanitize_error(error)
        assert "pass1" not in result
        assert "pass2" not in result
        assert "host1.com/repo" in result
        assert "host2.com/repo" in result

    def test_preserves_non_credential_urls(self, service):
        """Should preserve URLs without credentials"""
        error = "Unable to access https://github.com/org/repo.git"
        result = service._sanitize_error(error)
        assert result == error

    def test_handles_url_encoded_credentials(self, service):
        """Should handle URL-encoded special characters in credentials"""
        error = "fatal: https://user:p%40ss%2Fword@github.com/repo.git"
        result = service._sanitize_error(error)
        assert "p%40ss%2Fword" not in result
        assert "user:" not in result

    def test_handles_at_sign_in_password(self, service):
        """Should handle passwords containing @ characters"""
        error = "fatal: https://user:p@ss@github.com/repo.git"
        result = service._sanitize_error(error)
        # Should not leak any part of password
        assert "p@ss" not in result
        assert "user:" not in result
        assert "github.com/repo.git" in result

    def test_handles_multiple_at_signs_in_password(self, service):
        """Should handle passwords with multiple @ characters"""
        error = "fatal: https://user:p@ss@word@github.com/repo.git"
        result = service._sanitize_error(error)
        assert "p@ss@word" not in result
        assert "user:" not in result
        assert "github.com/repo.git" in result

    def test_sanitizes_ssh_urls(self, service):
        """Should sanitize ssh:// URLs with usernames"""
        error = "Permission denied (publickey) for ssh://deploy@github.com/repo.git"
        result = service._sanitize_error(error)
        assert "deploy@" not in result
        assert "github.com/repo.git" in result

    def test_sanitizes_git_at_urls(self, service):
        """Should mask usernames in git@ style URLs"""
        error = "Permission denied for git@github.com:org/repo.git"
        result = service._sanitize_error(error)
        assert "git@" not in result
        assert "***@github.com:org/repo.git" in result

    def test_sanitizes_ssh_key_paths(self, service):
        """Should hide SSH key file paths"""
        error = "Could not read from key file '/app/data/git-repos/.ssh-key-5-a1b2c3d4'"
        result = service._sanitize_error(error)
        assert ".ssh-key-5-" not in result
        assert "[SSH_KEY_FILE]" in result


class TestReadFile:
    """Tests for read_file method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_reads_existing_file(self, service, tmp_path):
        """Should return file contents for existing file"""
        # Create repo directory and file
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()
        test_file = repo_dir / "docker-compose.yml"
        test_file.write_text("version: '3'\nservices: {}")

        repo = Mock(id=1)
        result = service.read_file(repo, "docker-compose.yml")

        assert result == "version: '3'\nservices: {}"

    def test_returns_none_for_nonexistent_file(self, service, tmp_path):
        """Should return None for non-existent file"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()

        repo = Mock(id=1)
        result = service.read_file(repo, "nonexistent.yml")

        assert result is None

    def test_prevents_path_traversal(self, service, tmp_path):
        """Should return None for path traversal attempts"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()

        # Create file outside repo
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret data")

        repo = Mock(id=1)
        result = service.read_file(repo, "../secret.txt")

        assert result is None

    def test_rejects_symlinks(self, service, tmp_path):
        """Should return None for symlinks (TOCTOU protection)"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()

        # Create actual file and symlink
        real_file = repo_dir / "real.txt"
        real_file.write_text("real content")
        symlink = repo_dir / "link.txt"
        symlink.symlink_to(real_file)

        repo = Mock(id=1)
        result = service.read_file(repo, "link.txt")

        assert result is None  # Symlinks are rejected


class TestListComposeFiles:
    """Tests for list_compose_files method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_finds_yml_and_yaml_files(self, service, tmp_path):
        """Should find both .yml and .yaml compose files"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()
        (repo_dir / "docker-compose.yml").write_text("version: '3'")
        (repo_dir / "compose.yaml").write_text("version: '3'")
        (repo_dir / "other.txt").write_text("not compose")

        repo = Mock(id=1)
        result = service.list_compose_files(repo)

        assert len(result) == 2
        assert "docker-compose.yml" in result
        assert "compose.yaml" in result
        assert "other.txt" not in result

    def test_finds_nested_compose_files(self, service, tmp_path):
        """Should find compose files in subdirectories"""
        repo_dir = tmp_path / "repo-1"
        (repo_dir / "stacks" / "app1").mkdir(parents=True)
        (repo_dir / "stacks" / "app2").mkdir(parents=True)
        (repo_dir / "stacks" / "app1" / "docker-compose.yml").write_text("v1")
        (repo_dir / "stacks" / "app2" / "docker-compose.yml").write_text("v2")

        repo = Mock(id=1)
        result = service.list_compose_files(repo)

        assert len(result) == 2
        assert "stacks/app1/docker-compose.yml" in result
        assert "stacks/app2/docker-compose.yml" in result

    def test_returns_empty_list_for_nonexistent_repo(self, service):
        """Should return empty list if repo not cloned"""
        repo = Mock(id=999)
        result = service.list_compose_files(repo)
        assert result == []

    def test_returns_sorted_deduplicated_list(self, service, tmp_path):
        """Should return sorted list without duplicates"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()
        (repo_dir / "a-compose.yml").write_text("v")
        (repo_dir / "z-compose.yml").write_text("v")
        (repo_dir / "m-compose.yml").write_text("v")

        repo = Mock(id=1)
        result = service.list_compose_files(repo)

        assert result == sorted(result)


class TestCleanupRepo:
    """Tests for cleanup_repo method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_removes_existing_repo_directory(self, service, tmp_path):
        """Should remove repo directory and contents"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()
        (repo_dir / "file.txt").write_text("content")
        assert repo_dir.exists()

        service.cleanup_repo(1)
        assert not repo_dir.exists()

    def test_handles_nonexistent_repo(self, service):
        """Should not raise for non-existent repo"""
        service.cleanup_repo(999)  # Should not raise


class TestRepoExists:
    """Tests for repo_exists method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_returns_true_for_existing_repo(self, service, tmp_path):
        """Should return True when repo directory exists"""
        repo_dir = tmp_path / "repo-1"
        repo_dir.mkdir()

        assert service.repo_exists(1) is True

    def test_returns_false_for_nonexistent_repo(self, service):
        """Should return False when repo directory doesn't exist"""
        assert service.repo_exists(999) is False


class TestSyncResult:
    """Tests for SyncResult dataclass"""

    def test_success_sync_result(self):
        """Should create successful sync result"""
        result = SyncResult(success=True, updated=True, commit="abc123")
        assert result.success is True
        assert result.updated is True
        assert result.commit == "abc123"
        assert result.error is None

    def test_error_sync_result(self):
        """Should create error sync result"""
        result = SyncResult(success=False, updated=False, commit=None, error="Auth failed")
        assert result.success is False
        assert result.error == "Auth failed"


class TestClone:
    """Tests for clone() async method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_clone_success(self, service, tmp_path):
        """Should clone repository and return success result"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        mock_clone_result = Mock(returncode=0, stderr='')
        mock_commit_result = Mock(returncode=0, stdout='abc123def456\n')

        with patch.object(service, '_run_git', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [mock_clone_result, mock_commit_result]
            result = await service.clone(repo)

        assert result.success is True
        assert result.updated is True
        assert result.commit == 'abc123def456'

    @pytest.mark.asyncio
    async def test_clone_failure_returns_error(self, service, tmp_path):
        """Should return error result on clone failure"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        mock_result = Mock(returncode=128, stderr='fatal: repository not found')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result):
            result = await service.clone(repo)

        assert result.success is False
        assert result.updated is False
        assert 'repository not found' in result.error

    @pytest.mark.asyncio
    async def test_clone_delegates_to_pull_if_exists(self, service, tmp_path):
        """Should call pull() if repo already exists"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        # Create the repo directory so clone thinks it exists
        repo_dir = tmp_path / 'repo-1'
        repo_dir.mkdir()

        with patch.object(service, 'pull', new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = SyncResult(success=True, updated=False, commit='abc123')
            result = await service.clone(repo)

        mock_pull.assert_called_once_with(repo, None)
        assert result.success is True


class TestPull:
    """Tests for pull() async method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_pull_with_new_commits(self, service, tmp_path):
        """Should return updated=True when new commits are pulled"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        # Create the repo directory
        repo_dir = tmp_path / 'repo-1'
        repo_dir.mkdir()

        mock_old_commit = Mock(returncode=0, stdout='old123\n')
        mock_fetch = Mock(returncode=0, stderr='')
        mock_reset = Mock(returncode=0, stderr='')
        mock_new_commit = Mock(returncode=0, stdout='new456\n')

        with patch.object(service, '_run_git', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [mock_old_commit, mock_fetch, mock_reset, mock_new_commit]
            result = await service.pull(repo)

        assert result.success is True
        assert result.updated is True
        assert result.commit == 'new456'

    @pytest.mark.asyncio
    async def test_pull_no_changes(self, service, tmp_path):
        """Should return updated=False when no new commits"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        repo_dir = tmp_path / 'repo-1'
        repo_dir.mkdir()

        # Same commit before and after
        mock_commit = Mock(returncode=0, stdout='same123\n')
        mock_fetch = Mock(returncode=0, stderr='')
        mock_reset = Mock(returncode=0, stderr='')

        with patch.object(service, '_run_git', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [mock_commit, mock_fetch, mock_reset, mock_commit]
            result = await service.pull(repo)

        assert result.success is True
        assert result.updated is False

    @pytest.mark.asyncio
    async def test_pull_fetch_failure(self, service, tmp_path):
        """Should return error on fetch failure"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        repo_dir = tmp_path / 'repo-1'
        repo_dir.mkdir()

        mock_old_commit = Mock(returncode=0, stdout='old123\n')
        mock_fetch_fail = Mock(returncode=1, stderr='fatal: could not read from remote')

        with patch.object(service, '_run_git', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [mock_old_commit, mock_fetch_fail]
            result = await service.pull(repo)

        assert result.success is False
        assert 'could not read from remote' in result.error

    @pytest.mark.asyncio
    async def test_pull_delegates_to_clone_if_not_exists(self, service, tmp_path):
        """Should call clone() if repo doesn't exist"""
        repo = Mock(id=1, name='test-repo', url='https://github.com/org/repo.git',
                   branch='main', credential=None)

        with patch.object(service, 'clone', new_callable=AsyncMock) as mock_clone:
            mock_clone.return_value = SyncResult(success=True, updated=True, commit='abc123')
            result = await service.pull(repo)

        mock_clone.assert_called_once_with(repo, None)
        assert result.success is True


class TestTestConnection:
    """Tests for test_connection() async method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService instance with mocked git check"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_connection_success(self, service):
        """Should return success for accessible repository"""
        mock_result = Mock(returncode=0, stdout='abc123\trefs/heads/main')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result):
            success, message = await service.test_connection(
                'https://github.com/org/repo.git', 'main'
            )

        assert success is True
        assert 'successful' in message.lower()

    @pytest.mark.asyncio
    async def test_connection_failure(self, service):
        """Should return failure for inaccessible repository"""
        mock_result = Mock(returncode=128, stderr='fatal: repository not found')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result):
            success, message = await service.test_connection(
                'https://github.com/org/nonexistent.git', 'main'
            )

        assert success is False
        assert 'not found' in message.lower()

    @pytest.mark.asyncio
    async def test_connection_with_credentials(self, service):
        """Should use credentials when provided"""
        credential = Mock(auth_type='https', username='user', password='token', ssh_private_key=None)
        mock_result = Mock(returncode=0, stdout='abc123\trefs/heads/main')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result):
            with patch.object(service, '_build_auth_url', return_value='https://user:token@github.com/org/repo.git') as mock_build:
                success, _ = await service.test_connection(
                    'https://github.com/org/repo.git', 'main', credential
                )

        mock_build.assert_called_once()
        assert success is True

    @pytest.mark.asyncio
    async def test_connection_with_ssh_credentials(self, service):
        """Should use SSH credentials when provided"""
        credential = Mock(
            id='cred-123',
            auth_type='ssh',
            username=None,
            password=None,
            ssh_private_key='-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----'
        )
        mock_result = Mock(returncode=0, stdout='abc123\trefs/heads/main')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result) as mock_git:
            with patch.object(service, '_build_git_env', return_value=({'GIT_SSH_COMMAND': 'ssh -i /tmp/key'}, Path('/tmp/key'))) as mock_env:
                with patch.object(service, '_cleanup_ssh_key') as mock_cleanup:
                    success, _ = await service.test_connection(
                        'git@github.com:org/repo.git', 'main', credential
                    )

        mock_env.assert_called_once()
        mock_cleanup.assert_called_once()
        assert success is True


class TestListFiles:
    """Tests for list_files method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService with temp directory"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_rejects_path_traversal_pattern(self, service, tmp_path):
        """Should reject patterns containing path traversal sequences"""
        # Note: get_repo_path() prepends "repo-" to the ID
        repo = Mock(id=123)
        repo_path = tmp_path / 'repo-123'
        repo_path.mkdir()

        # Create a file that would match if traversal worked
        (repo_path / 'secret.txt').write_text('secret')

        result = service.list_files(repo, '../secret.txt')
        assert result == []

        result = service.list_files(repo, '../../etc/passwd')
        assert result == []

        result = service.list_files(repo, 'foo/../bar.txt')
        assert result == []

    def test_returns_matching_files(self, service, tmp_path):
        """Should return files matching the pattern"""
        # Note: get_repo_path() prepends "repo-" to the ID
        repo = Mock(id=123)
        repo_path = tmp_path / 'repo-123'
        repo_path.mkdir()

        # Create test files
        (repo_path / 'config.env').write_text('KEY=value')
        (repo_path / 'local.env').write_text('LOCAL=true')
        (repo_path / 'config.yml').write_text('config: true')

        result = service.list_files(repo, '*.env')
        assert 'config.env' in result
        assert 'local.env' in result
        assert 'config.yml' not in result

    def test_returns_empty_for_nonexistent_repo(self, service):
        """Should return empty list if repo doesn't exist"""
        repo = Mock(id=99999)  # No directory created for this ID

        result = service.list_files(repo, '*.txt')
        assert result == []

    def test_filters_symlinks_outside_repo(self, service, tmp_path):
        """Should filter out symlinks pointing outside repo"""
        # Note: get_repo_path() prepends "repo-" to the ID
        repo = Mock(id=123)
        repo_path = tmp_path / 'repo-123'
        repo_path.mkdir()

        # Create a file inside repo
        (repo_path / 'real.env').write_text('real')

        # Create a symlink pointing outside repo
        outside_file = tmp_path / 'outside.env'
        outside_file.write_text('outside')
        symlink_path = repo_path / 'link.env'
        symlink_path.symlink_to(outside_file)

        result = service.list_files(repo, '*.env')
        assert 'real.env' in result
        # Symlink should be filtered out because it resolves outside repo
        assert 'link.env' not in result


class TestPullResetFailure:
    """Tests for pull() reset failure path"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService with temp directory"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_pull_reset_failure(self, service, tmp_path):
        """Should handle reset failure after successful fetch"""
        repo = Mock(id='repo-123', branch='main', credential=None, url='https://github.com/org/repo.git')
        repo_path = tmp_path / 'repo-123'
        repo_path.mkdir()

        # Mock git operations: fetch succeeds, reset fails
        fetch_result = Mock(returncode=0)
        reset_result = Mock(returncode=1, stderr='error: could not reset')

        async def mock_run_git(cmd, **kwargs):
            # cmd is a list like ['fetch', 'origin', 'main'] or ['reset', '--hard', 'origin/main']
            cmd_str = ' '.join(cmd)
            if 'fetch' in cmd_str:
                return fetch_result
            elif 'reset' in cmd_str:
                return reset_result
            elif 'rev-parse' in cmd_str:
                return Mock(returncode=0, stdout='abc123')
            return Mock(returncode=0)

        with patch.object(service, '_run_git', side_effect=mock_run_git):
            result = await service.pull(repo)

        assert result.success is False
        assert 'reset' in result.error.lower()


class TestBranchValidation:
    """Tests for branch validation in clone/pull"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService with temp directory"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_clone_without_branch_fails(self, service):
        """Should fail if no branch specified for clone"""
        repo = Mock(id='repo-123', branch=None, credential=None, url='https://github.com/org/repo.git')

        result = await service.clone(repo, branch=None)

        assert result.success is False
        assert 'no branch' in result.error.lower()

    @pytest.mark.asyncio
    async def test_pull_without_branch_fails(self, service, tmp_path):
        """Should fail if no branch specified for pull"""
        repo = Mock(id='repo-123', branch=None, credential=None, url='https://github.com/org/repo.git')
        # Create repo path so pull doesn't delegate to clone
        repo_path = tmp_path / 'repo-123'
        repo_path.mkdir()

        result = await service.pull(repo, branch=None)

        assert result.success is False
        assert 'no branch' in result.error.lower()

    @pytest.mark.asyncio
    async def test_clone_with_empty_branch_fails(self, service):
        """Should fail if branch is empty string"""
        repo = Mock(id='repo-123', branch='', credential=None, url='https://github.com/org/repo.git')

        result = await service.clone(repo)

        assert result.success is False
        assert 'no branch' in result.error.lower()


class TestBuildAuthUrl:
    """Tests for _build_auth_url method"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService with temp directory"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    def test_malformed_url_no_hostname(self, service):
        """Should return original URL if hostname is missing"""
        credential = Mock(auth_type='https', username='user', password='pass')

        # URL without hostname
        result = service._build_auth_url('https://', credential)
        assert result == 'https://'

        # URL with path but no hostname
        result = service._build_auth_url('https:///path/to/repo', credential)
        assert result == 'https:///path/to/repo'

    def test_valid_url_with_credentials(self, service):
        """Should embed credentials in valid URL"""
        credential = Mock(auth_type='https', username='user', password='token123')

        result = service._build_auth_url('https://github.com/org/repo.git', credential)
        assert 'user:token123@github.com' in result


class TestTimeoutHandling:
    """Tests for timeout handling in git operations"""

    @pytest.fixture
    def service(self, tmp_path):
        """Create GitService with temp directory"""
        with patch.object(GitService, '_verify_git_available'):
            return GitService(repos_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_clone_uses_long_timeout(self, service, tmp_path):
        """Should use 600s timeout for clone operations"""
        repo = Mock(id='repo-123', branch='main', credential=None, url='https://github.com/org/repo.git')
        mock_result = Mock(returncode=0, stdout='', stderr='')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result) as mock_git:
            with patch.object(service, '_get_head_commit', new_callable=AsyncMock, return_value='abc123'):
                await service.clone(repo)

        # Verify clone was called with 600s timeout
        call_args = mock_git.call_args
        assert call_args.kwargs.get('timeout') == 600

    @pytest.mark.asyncio
    async def test_test_connection_uses_short_timeout(self, service):
        """Should use 30s timeout for test_connection"""
        mock_result = Mock(returncode=0, stdout='abc123\trefs/heads/main')

        with patch.object(service, '_run_git', new_callable=AsyncMock, return_value=mock_result) as mock_git:
            await service.test_connection('https://github.com/org/repo.git', 'main')

        # Verify ls-remote was called with 30s timeout
        call_args = mock_git.call_args
        assert call_args.kwargs.get('timeout') == 30
