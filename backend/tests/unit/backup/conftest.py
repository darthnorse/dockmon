import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet

from backup.crypto import KdfParams
from backup.paths import BackupPaths
from backup.validate import ALEMBIC_DIR
from manage_backup import migrate_candidate

BACKEND_DIR = Path(__file__).parents[3]
_SCRIPT = ScriptDirectory(str(ALEMBIC_DIR))
HEAD_REVISION = _SCRIPT.get_current_head()
OLDER_REVISION = _SCRIPT.get_revision(HEAD_REVISION).down_revision
PASSPHRASE = "correct horse battery staple"
FAST_KDF = KdfParams(n_log2=10, r=8, p=1)

WEB_COMPOSE = """services:
  app:
    image: nginx
    env_file:
      - app.env
    volumes:
      - ./data:/data
"""


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


@pytest.fixture(scope="session")
def head_db_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("templates") / "head.db"
    assert migrate_candidate(path)
    return path


@pytest.fixture(scope="session")
def older_db_template(head_db_template, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("templates") / "older.db"
    shutil.copy2(head_db_template, path)
    command.downgrade(_alembic_config(path), OLDER_REVISION)
    return path


@pytest.fixture
def migrate_to_head():
    return migrate_candidate


def seed_database(db_path: Path, key: bytes, host_name: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO docker_hosts (id, name, url, is_podman, connection_type) "
        "VALUES (?, ?, 'unix:///var/run/docker.sock', 0, 'local')",
        (f"host-{host_name}", host_name),
    )
    conn.execute(
        "INSERT INTO registry_credentials (registry_url, username, password_encrypted, created_at, updated_at) "
        "VALUES ('ghcr.io', 'me', ?, '2026-01-01', '2026-01-01')",
        (Fernet(key).encrypt(b"registry-secret").decode(),),
    )
    conn.execute(
        "INSERT INTO container_stats_history (container_id, host_id, timestamp, resolution) "
        "VALUES ('abc123def456', ?, 1, '1h')",
        (f"host-{host_name}",),
    )
    conn.execute(
        "INSERT INTO host_stats_history (host_id, timestamp, resolution) VALUES (?, 1, '1h')",
        (f"host-{host_name}",),
    )
    conn.commit()
    conn.close()


def host_names(db_path: Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT name FROM docker_hosts"))
    finally:
        conn.close()


def build_install(root: Path, template: Path, host_name: str, env_value: str) -> BackupPaths:
    data = root / "data"
    stacks = data / "stacks"
    data.mkdir(parents=True)
    key = Fernet.generate_key()
    paths = BackupPaths(
        data_dir=data,
        db_path=data / "dockmon.db",
        key_path=data / "encryption.key",
        stacks_dir=stacks,
        certs_dir=data / "certs",
        session_secret_path=data / ".session_secret",
    )
    shutil.copy2(template, paths.db_path)
    seed_database(paths.db_path, key, host_name)
    paths.key_path.write_bytes(key)
    os.chmod(paths.key_path, 0o600)

    web = stacks / "web"
    (web / "data").mkdir(parents=True)
    (web / "compose.yaml").write_text(WEB_COMPOSE)
    (web / ".env").write_text(f"A={env_value}\n")
    (web / "app.env").write_text(f"B={env_value}\n")
    (web / ".env.prod").write_text(f"C={env_value}\n")
    (web / "data" / "db.sqlite").write_text(f"bind mount data {env_value}")
    (web / "notes.txt").write_text("not an env file")
    os.symlink("/etc/hostname", web / "link.env")

    api = stacks / "api"
    api.mkdir()
    (api / "docker-compose.yml").write_text(f"services:\n  api:\n    image: api:{env_value}\n")

    bad = stacks / "Bad Name"
    bad.mkdir()
    (bad / "compose.yaml").write_text("services: {}\n")

    (paths.certs_dir / "host-x").mkdir(parents=True)
    (paths.certs_dir / "host-x" / "cert.pem").write_text("cert")
    paths.session_secret_path.write_text("secret")
    (data / "stats-service-token").write_text("token")
    (data / "logs").mkdir()
    (data / "logs" / "dockmon.log").write_text("log")
    return paths


@pytest.fixture
def install(tmp_path, head_db_template) -> BackupPaths:
    return build_install(tmp_path / "source", head_db_template, "source-host", "old")
