import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import database as database_module
from backup.errors import BackupConflictError, BackupDecryptError
from backup.schedule_store import (
    read_schedule,
    record_run,
    reset_after_restore,
    stored_passphrase,
    update_schedule,
)
from backup.scheduled import ScheduledRun
from database import DatabaseManager, GlobalSettings


@pytest.fixture
def db(tmp_path):
    database_module._database_manager_instance = None
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    try:
        yield manager
    finally:
        manager.engine.dispose()
        database_module._database_manager_instance = None


def test_defaults(db):
    schedule = read_schedule(db)
    assert schedule.enabled is False
    assert schedule.schedule == "03:00"
    assert schedule.retention == 7
    assert schedule.include_stats is True
    assert schedule.passphrase_set is False
    assert schedule.last_run_at is None


def test_passphrase_is_stored_encrypted_and_never_readable_back_as_plaintext(db, tmp_path):
    update_schedule(db, passphrase="nas-backup-passphrase", enabled=True)

    assert read_schedule(db).passphrase_set is True
    assert stored_passphrase(db) == "nas-backup-passphrase"
    conn = sqlite3.connect(db.db_path)
    raw = conn.execute("SELECT backup_passphrase_encrypted FROM global_settings").fetchone()[0]
    conn.close()
    assert raw and "nas-backup-passphrase" not in raw


def test_enabling_needs_a_passphrase(db):
    with pytest.raises(BackupConflictError):
        update_schedule(db, enabled=True)


def test_clearing_the_passphrase_is_refused_while_enabled(db):
    update_schedule(db, passphrase="nas-backup-passphrase", enabled=True)
    with pytest.raises(BackupConflictError):
        update_schedule(db, clear_passphrase=True)
    update_schedule(db, enabled=False)
    update_schedule(db, clear_passphrase=True)
    assert read_schedule(db).passphrase_set is False


def test_undecryptable_passphrase_has_a_fixed_message(db):
    with db.get_session() as session:
        settings = session.query(GlobalSettings).first()
        settings.backup_passphrase_encrypted = "not-a-fernet-token"
        session.commit()
    with pytest.raises(BackupDecryptError, match="set it again"):
        stored_passphrase(db)


def test_record_run_and_reset_after_restore(db):
    at = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)
    record_run(db, ScheduledRun(status="failed", error="The backup destination does not exist"), at)
    schedule = read_schedule(db)
    assert schedule.last_status == "failed"
    assert schedule.last_error == "The backup destination does not exist"
    assert schedule.last_run_at == at

    restored_at = at + timedelta(days=1)
    reset_after_restore(db, restored_at)
    schedule = read_schedule(db)
    assert schedule.last_run_at == restored_at
    assert schedule.last_status is None and schedule.last_error is None and schedule.last_file is None


def test_deleting_the_last_file_clears_it(db):
    at = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)
    record_run(db, ScheduledRun(status="ok", file="a.dmbak"), at)
    update_schedule(db, forget_last_file="b.dmbak")
    assert read_schedule(db).last_file == "a.dmbak"
    update_schedule(db, forget_last_file="a.dmbak")
    assert read_schedule(db).last_file is None
