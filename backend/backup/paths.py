import os
from dataclasses import dataclass
from pathlib import Path

from config.paths import CERTS_DIR, DATA_DIR, DATABASE_PATH, DEFAULT_SESSION_SECRET_FILE
from deployment.stack_storage import STACKS_DIR
from utils.encryption import KEY_PATH

RESTORE_DIRNAME = ".dockmon-restore"


@dataclass(frozen=True)
class BackupPaths:
    """Every location backup and restore read or replace.

    Each is resolved from its own setting because DATABASE_PATH, STACKS_DIR and
    SESSION_SECRET_FILE can each point outside DATA_DIR.
    """

    data_dir: Path
    db_path: Path
    key_path: Path
    stacks_dir: Path
    certs_dir: Path
    session_secret_path: Path

    @classmethod
    def from_environment(cls) -> "BackupPaths":
        return cls(
            data_dir=Path(DATA_DIR),
            db_path=Path(os.environ.get("DATABASE_PATH", DATABASE_PATH)),
            key_path=Path(KEY_PATH),
            stacks_dir=STACKS_DIR,
            certs_dir=Path(CERTS_DIR),
            session_secret_path=Path(os.getenv("SESSION_SECRET_FILE", DEFAULT_SESSION_SECRET_FILE)),
        )

    @property
    def backup_tmp_dir(self) -> Path:
        return self.data_dir / ".backup-tmp"

    @property
    def restore_dir(self) -> Path:
        return self.data_dir / RESTORE_DIRNAME

    @property
    def pending_dir(self) -> Path:
        return self.restore_dir / "pending"

    @property
    def upload_dir(self) -> Path:
        return self.restore_dir / "upload"

    @property
    def journal_path(self) -> Path:
        return self.restore_dir / "journal.json"

    @property
    def completed_marker(self) -> Path:
        return self.restore_dir / "completed.json"
