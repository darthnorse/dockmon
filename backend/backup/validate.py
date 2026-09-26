"""Validate a decrypted backup before anything live is touched."""

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tarfile
import unicodedata
import zlib
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet, InvalidToken

from backup.archive import (
    DB_NAME,
    FREE_SPACE_MARGIN,
    KEY_NAME,
    MANIFEST_FORMAT_VERSION,
    MANIFEST_NAME,
    MAX_DB_BYTES,
    MAX_KEY_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_MEMBERS,
    MAX_STACK_FILE_BYTES,
    MAX_TOTAL_BYTES,
    STACKS_PREFIX,
)
from backup.errors import BackupError, BackupSpaceError, BackupValidationError
from backup.fsutil import IO_BLOCK, write_new_file
from deployment.stack_storage import COMPOSE_FILENAMES, validate_stack_name
from utils.env_files import is_safe_env_filename

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

REQUIRED_TABLES = ("alembic_version", "users", "docker_hosts", "global_settings", "custom_groups")
ENCRYPTED_COLUMNS = (
    ("registry_credentials", "password_encrypted"),
    ("oidc_config", "client_secret_encrypted"),
    ("global_settings", "backup_passphrase_encrypted"),
)

_STACK_MEMBER = re.compile(rf"^{STACKS_PREFIX}/([^/]+)/([^/]+)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
MAX_APP_VERSION_LENGTH = 64


@lru_cache(maxsize=1)
def known_revisions() -> frozenset:
    """Every schema revision this build can migrate from (single-head chain)."""
    script = ScriptDirectory(str(ALEMBIC_DIR))
    if len(script.get_heads()) != 1:
        raise BackupError("Migration history has multiple heads; cannot validate backups")
    return frozenset(rev.revision for rev in script.walk_revisions())


def check_member_name(name: str) -> None:
    if "\x00" in name or unicodedata.normalize("NFC", name) != name:
        raise BackupValidationError(f"Unexpected file in backup archive: {name!r}")
    if name in (MANIFEST_NAME, DB_NAME, KEY_NAME):
        return
    match = _STACK_MEMBER.match(name)
    if not match:
        raise BackupValidationError(f"Unexpected file in backup archive: {name!r}")
    stack, filename = match.groups()
    try:
        validate_stack_name(stack)
    except ValueError:
        raise BackupValidationError(f"Invalid stack name in backup archive: {stack!r}") from None
    if filename not in COMPOSE_FILENAMES and not is_safe_env_filename(filename):
        raise BackupValidationError(f"Unexpected file in backup archive: {name!r}")


def _size_limit(name: str) -> int:
    if name == MANIFEST_NAME:
        return MAX_MANIFEST_BYTES
    if name == DB_NAME:
        return MAX_DB_BYTES
    if name == KEY_NAME:
        return MAX_KEY_BYTES
    return MAX_STACK_FILE_BYTES


def parse_manifest(data: bytes) -> dict:
    try:
        manifest = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise BackupValidationError("Backup manifest is not valid JSON") from None
    if not isinstance(manifest, dict):
        raise BackupValidationError("Backup manifest is malformed")
    if manifest.get("format_version") != MANIFEST_FORMAT_VERSION:
        raise BackupValidationError(
            f"Unsupported backup format version {manifest.get('format_version')!r}"
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or DB_NAME not in files or KEY_NAME not in files:
        raise BackupValidationError("Backup manifest is missing its file list")
    for name, entry in files.items():
        check_member_name(name)
        if name == MANIFEST_NAME:
            raise BackupValidationError("Backup manifest lists itself")
        if (
            not isinstance(entry, dict)
            or not _is_count(entry.get("size"))
            or entry["size"] > _size_limit(name)
            or not isinstance(entry.get("sha256"), str)
            or not _SHA256.match(entry["sha256"])
        ):
            raise BackupValidationError(f"Backup manifest entry for {name} is malformed")
    if not isinstance(manifest.get("alembic_revision"), str):
        raise BackupValidationError("Backup manifest is missing alembic_revision")
    if not isinstance(manifest.get("created_at"), str) or not _UTC_TIMESTAMP.match(manifest["created_at"]):
        raise BackupValidationError("Backup manifest has an invalid created_at")
    app_version = manifest.get("app_version")
    if not isinstance(app_version, str) or len(app_version) > MAX_APP_VERSION_LENGTH:
        raise BackupValidationError("Backup manifest has an invalid app_version")
    _check_summary(manifest.get("summary"))
    return manifest


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_summary(summary) -> None:
    if not isinstance(summary, dict) or not all(
        _is_count(summary.get(field)) for field in ("hosts", "users", "alert_rules")
    ):
        raise BackupValidationError("Backup manifest summary is malformed")
    stacks = summary.get("stacks")
    if not isinstance(stacks, list):
        raise BackupValidationError("Backup manifest summary is malformed")
    for stack in stacks:
        try:
            validate_stack_name(stack)
        except (ValueError, TypeError):
            raise BackupValidationError("Backup manifest summary names an invalid stack") from None


def _make_private_dirs(root: Path, relative_parent: Path) -> None:
    current = root
    for part in relative_parent.parts:
        current = current / part
        current.mkdir(mode=0o700, exist_ok=True)


def _extract_member(tf: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> str:
    digest = hashlib.sha256()
    source = tf.extractfile(member)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        for block in iter(lambda: source.read(IO_BLOCK), b""):
            digest.update(block)
            out.write(block)
        out.flush()
        os.fsync(out.fileno())
    return digest.hexdigest()


def extract_archive(tar_path: Path, dest_dir: Path) -> dict:
    """Extract an allowlisted, manifest-verified archive into a new dest_dir.

    Returns the manifest. Never uses extractall and never trusts member modes,
    owners or link targets: only regular files with allowlisted names are
    written, each checked against the manifest's size and SHA-256.
    """
    dest_dir.mkdir(mode=0o700, parents=True)
    try:
        tf = tarfile.open(tar_path, "r|gz")
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error) as e:
        raise BackupValidationError("Backup archive is not readable") from e

    manifest = None
    seen = set()
    total = 0
    try:
        with tf:
            for count, member in enumerate(tf, start=1):
                if count > MAX_MEMBERS:
                    raise BackupValidationError("Backup archive has too many files")
                if not member.isreg() or member.pax_headers:
                    raise BackupValidationError(f"Backup archive contains a non-regular entry: {member.name!r}")
                check_member_name(member.name)
                if member.name in seen:
                    raise BackupValidationError(f"Duplicate file in backup archive: {member.name}")
                seen.add(member.name)
                if member.size > _size_limit(member.name):
                    raise BackupValidationError(f"{member.name} is too large")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise BackupValidationError("Backup archive is too large")

                if manifest is None:
                    if member.name != MANIFEST_NAME:
                        raise BackupValidationError("Backup archive does not start with its manifest")
                    manifest = parse_manifest(tf.extractfile(member).read())
                    _check_room_for(manifest, dest_dir)
                    continue

                expected = manifest["files"].get(member.name)
                if expected is None:
                    raise BackupValidationError(f"{member.name} is not listed in the backup manifest")
                if member.size != expected["size"]:
                    raise BackupValidationError(f"{member.name} size does not match the backup manifest")
                relative = Path(member.name)
                _make_private_dirs(dest_dir, relative.parent)
                digest = _extract_member(tf, member, dest_dir / relative)
                if member.size != expected["size"] or digest != expected["sha256"]:
                    raise BackupValidationError(f"{member.name} failed its checksum")
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error) as e:
        raise BackupValidationError("Backup archive is corrupted") from e

    if manifest is None:
        raise BackupValidationError("Backup archive is empty")
    missing = sorted(set(manifest["files"]) - seen)
    if missing:
        raise BackupValidationError(f"Backup archive is missing: {', '.join(missing)}")

    write_new_file(dest_dir / MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True).encode())
    return manifest


def _check_room_for(manifest: dict, dest_dir: Path) -> None:
    """Reserve the declared total up front: sizes are attacker-chosen and gzip
    compresses padding ~1000:1, so a small upload must not fill the data volume."""
    declared = sum(entry["size"] for entry in manifest["files"].values())
    if declared > MAX_TOTAL_BYTES:
        raise BackupValidationError("Backup archive is too large")
    if shutil.disk_usage(dest_dir).free < declared + FREE_SPACE_MARGIN:
        raise BackupSpaceError("Not enough free disk space to extract the backup")


def check_database(db_path: Path, key: bytes, expected_revision: str) -> None:
    """Integrity, schema revision, foreign keys, and that key decrypts the credentials."""
    try:
        fernet = Fernet(key)
    except (ValueError, TypeError):
        raise BackupValidationError("Backup encryption key is invalid") from None

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupValidationError("Backup database failed its integrity check")

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise BackupValidationError(f"Backup database is missing tables: {', '.join(missing)}")

        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(rows) != 1:
            raise BackupValidationError("Backup database has no single schema revision")
        revision = rows[0][0]
        if revision != expected_revision:
            raise BackupValidationError("Backup database revision does not match its manifest")
        if revision not in known_revisions():
            raise BackupValidationError(
                f"Backup was made by a newer DockMon (schema {revision}); upgrade DockMon first"
            )

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise BackupValidationError(f"Backup database has {len(violations)} foreign key violations")

        for table, column in ENCRYPTED_COLUMNS:
            if table not in tables or column not in {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}:
                continue
            query = f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
            for (value,) in conn.execute(query):
                try:
                    fernet.decrypt(value.encode("ascii"))
                except (InvalidToken, UnicodeEncodeError, AttributeError):
                    raise BackupValidationError(
                        "Backup encryption key does not decrypt its stored credentials"
                    ) from None
    except sqlite3.DatabaseError as e:
        raise BackupValidationError("Backup database is corrupted") from e
    finally:
        if conn is not None:
            conn.close()
