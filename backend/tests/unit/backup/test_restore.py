import io
import os
import shutil
import sqlite3
import stat
from pathlib import Path

import pytest

from backup import restore
from backup.archive import create_backup
from backup.errors import BackupDecryptError, BackupError, RestoreStateError
from backup.restore import (
    ApplyOutcome,
    apply_staged,
    cancel_staged,
    delete_rollback,
    list_rollbacks,
    pending_manifest,
    stage_archive,
    stage_rollback,
    verify_archive,
)
from tests.unit.backup.conftest import (
    FAST_KDF,
    HEAD_REVISION,
    OLDER_REVISION,
    PASSPHRASE,
    build_install,
    host_names,
)


class SimulatedCrash(BaseException):
    """Stands in for power loss: not an Exception, so apply cannot catch it."""


@pytest.fixture
def archive_file(tmp_path, head_db_template) -> Path:
    """A backup of a *different* install ('backup-host', env 'new')."""
    source = build_install(tmp_path / "backup-source", head_db_template, "backup-host", "new")
    (source.stacks_dir / "web" / "extra.env").write_text("X=new\n")
    compose = (source.stacks_dir / "web" / "compose.yaml").read_text()
    (source.stacks_dir / "web" / "compose.yaml").write_text(
        compose.replace("      - app.env\n", "      - app.env\n      - extra.env\n")
    )
    worker = source.stacks_dir / "worker"
    worker.mkdir()
    (worker / "compose.yaml").write_text("services:\n  w:\n    image: worker\n")
    path = tmp_path / "backup.dmbak"
    with open(path, "wb") as f:
        create_backup(source, f, PASSPHRASE, kdf=FAST_KDF)
    return path


@pytest.fixture
def target(install):
    """The live install being restored over ('source-host', env 'old')."""
    (install.stacks_dir / "local-only").mkdir()
    (install.stacks_dir / "local-only" / "compose.yaml").write_text("services: {}\n")
    return install


def ok_migrate(_path: Path) -> bool:
    return True


def _state(paths) -> dict:
    stacks = paths.stacks_dir
    return {
        "hosts": host_names(paths.db_path),
        "key": paths.key_path.read_bytes(),
        "web_env": (stacks / "web" / ".env").read_text(),
        "web_extra": (stacks / "web" / "extra.env").read_text() if (stacks / "web" / "extra.env").exists() else None,
        "api": (stacks / "api" / "docker-compose.yml").read_text(),
        "worker": (stacks / "worker" / "compose.yaml").exists(),
    }


def _assert_old(paths, old_key):
    s = _state(paths)
    assert s["hosts"] == ["source-host"]
    assert s["key"] == old_key
    assert s["web_env"] == "A=old\n"
    assert s["web_extra"] is None
    assert "api:old" in s["api"]
    assert s["worker"] is False


def _assert_new(paths, old_key):
    s = _state(paths)
    assert s["hosts"] == ["backup-host"]
    assert s["key"] != old_key
    assert s["web_env"] == "A=new\n"
    assert s["web_extra"] == "X=new\n"
    assert "api:new" in s["api"]
    assert s["worker"] is True


def _restore_root(paths) -> Path:
    return paths.data_dir / ".dockmon-restore"


def test_stage_validates_and_leaves_live_data_untouched(target, archive_file):
    old_key = target.key_path.read_bytes()

    manifest = stage_archive(target, archive_file, PASSPHRASE)

    assert manifest["summary"]["hosts"] == 1
    assert pending_manifest(target)["created_at"] == manifest["created_at"]
    _assert_old(target, old_key)


def test_stage_wrong_passphrase_leaves_nothing_behind(target, archive_file):
    with pytest.raises(BackupDecryptError):
        stage_archive(target, archive_file, "wrong passphrase!!")
    assert pending_manifest(target) is None
    upload = _restore_root(target) / "upload"
    assert not upload.exists() or not any(upload.iterdir())


def test_stage_refuses_to_replace_a_pending_restore(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    with pytest.raises(BackupError, match="already staged"):
        stage_archive(target, archive_file, PASSPHRASE)
    stage_archive(target, archive_file, PASSPHRASE, replace=True)


def test_cancel_removes_the_staged_restore(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    assert cancel_staged(target) is True
    assert pending_manifest(target) is None
    assert cancel_staged(target) is False


def test_apply_without_staged_restore_is_a_noop(target):
    assert apply_staged(target, ok_migrate) is ApplyOutcome.NONE


def test_apply_swaps_in_the_backup(target, archive_file):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)

    assert apply_staged(target, ok_migrate) is ApplyOutcome.APPLIED

    _assert_new(target, old_key)
    assert stat.S_IMODE(target.db_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.key_path.stat().st_mode) == 0o600


def test_apply_never_touches_files_outside_the_archive(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)

    web = target.stacks_dir / "web"
    assert (web / "data" / "db.sqlite").read_text() == "bind mount data old"
    assert (web / "notes.txt").read_text() == "not an env file"
    assert os.path.islink(web / "link.env")
    assert (target.stacks_dir / "local-only" / "compose.yaml").exists()


def test_apply_clears_derived_state_and_cleans_up(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)

    assert not target.certs_dir.exists()
    assert not target.session_secret_path.exists()
    assert pending_manifest(target) is None
    assert not (_restore_root(target) / "journal.json").exists()
    assert not (_restore_root(target) / "staged").exists()
    assert not (target.stacks_dir / ".dockmon-restore" / "staged").exists()
    assert (_restore_root(target) / "completed.json").exists()


def test_stale_wal_of_the_old_database_is_parked(target, archive_file):
    keep_open = sqlite3.connect(target.db_path)
    keep_open.execute("PRAGMA wal_autocheckpoint=0")
    keep_open.execute("UPDATE docker_hosts SET name = 'source-host'")
    keep_open.commit()
    assert Path(f"{target.db_path}-wal").exists()
    stage_archive(target, archive_file, PASSPHRASE)

    apply_staged(target, ok_migrate)
    keep_open.close()

    assert host_names(target.db_path) == ["backup-host"]
    [rollback] = list_rollbacks(target)
    parked_wal = _restore_root(target) / f"rollback-{rollback['id']}" / "dockmon.db-wal"
    assert parked_wal.exists()


def test_migration_runs_on_a_candidate_before_live_data_changes(target, archive_file):
    old_key = target.key_path.read_bytes()
    seen = []

    def migrate(candidate: Path) -> bool:
        seen.append(candidate)
        _assert_old(target, old_key)
        assert candidate != target.db_path
        assert host_names(candidate) == ["backup-host"]
        return True

    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, migrate)
    assert len(seen) == 1


def test_real_migration_of_an_older_backup(tmp_path, older_db_template, target, migrate_to_head):
    source = build_install(tmp_path / "older-source", older_db_template, "backup-host", "new")
    archive_path = tmp_path / "older.dmbak"
    with open(archive_path, "wb") as f:
        manifest = create_backup(source, f, PASSPHRASE, kdf=FAST_KDF)
    assert manifest["alembic_revision"] == OLDER_REVISION

    stage_archive(target, archive_path, PASSPHRASE)
    assert apply_staged(target, migrate_to_head) is ApplyOutcome.APPLIED

    conn = sqlite3.connect(target.db_path)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD_REVISION
    conn.close()


def test_failed_migration_cancels_restore_and_keeps_live_data(target, archive_file):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)

    assert apply_staged(target, lambda _p: False) is ApplyOutcome.FAILED

    _assert_old(target, old_key)
    assert pending_manifest(target) is None
    assert any(p.name.startswith("failed-") for p in _restore_root(target).iterdir())
    assert list_rollbacks(target) == []


def test_candidate_corrupted_by_migration_is_rejected(target, archive_file):
    old_key = target.key_path.read_bytes()

    def corrupting_migrate(candidate: Path) -> bool:
        data = bytearray(candidate.read_bytes())
        data[len(data) // 2 : len(data) // 2 + 4096] = b"\xff" * 4096
        candidate.write_bytes(bytes(data))
        return True

    stage_archive(target, archive_file, PASSPHRASE)
    assert apply_staged(target, corrupting_migrate) is ApplyOutcome.FAILED
    _assert_old(target, old_key)


def test_exception_during_swap_rolls_back(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    real_move = restore._move
    calls = []

    def flaky_move(src, dst):
        calls.append(1)
        if len(calls) == 4:
            raise OSError("I/O error")
        real_move(src, dst)

    monkeypatch.setattr(restore, "_move", flaky_move)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    _assert_old(target, old_key)
    assert not (_restore_root(target) / "journal.json").exists()


def test_rollback_failure_raises_and_keeps_the_journal(target, archive_file, monkeypatch):
    stage_archive(target, archive_file, PASSPHRASE)
    real_move = restore._move
    calls = []

    def failing_after_three(src, dst):
        calls.append(1)
        if len(calls) > 3:
            raise OSError("disk gone")
        real_move(src, dst)

    monkeypatch.setattr(restore, "_move", failing_after_three)
    with pytest.raises(RestoreStateError):
        apply_staged(target, ok_migrate)
    assert (_restore_root(target) / "journal.json").exists()


FS_STEPS = ("_move", "_remove", "_write_json_atomic")


def _count_steps(monkeypatch, crash_after=None) -> list:
    counter = []
    for name in FS_STEPS:
        real = getattr(restore, name)

        def wrapped(*args, _real=real, **kwargs):
            result = _real(*args, **kwargs)
            counter.append(1)
            if crash_after is not None and len(counter) == crash_after:
                raise SimulatedCrash()
            return result

        monkeypatch.setattr(restore, name, wrapped)
    return counter


def _total_steps(tmp_path, head_db_template, archive_file, monkeypatch) -> int:
    paths = build_install(tmp_path / "probe", head_db_template, "source-host", "old")
    stage_archive(paths, archive_file, PASSPHRASE)
    with monkeypatch.context() as m:
        counter = _count_steps(m)
        apply_staged(paths, ok_migrate)
    return len(counter)


def test_power_loss_at_every_step_ends_fully_old_or_fully_new(
    tmp_path, head_db_template, archive_file, monkeypatch
):
    total = _total_steps(tmp_path, head_db_template, archive_file, monkeypatch)
    assert total > 10

    outcomes = set()
    for crash_after in range(1, total + 1):
        paths = build_install(tmp_path / f"crash-{crash_after}", head_db_template, "source-host", "old")
        old_key = paths.key_path.read_bytes()
        stage_archive(paths, archive_file, PASSPHRASE)

        with monkeypatch.context() as m:
            _count_steps(m, crash_after=crash_after)
            with pytest.raises(SimulatedCrash):
                apply_staged(paths, ok_migrate)

        outcome = apply_staged(paths, ok_migrate)
        if outcome in (ApplyOutcome.APPLIED, ApplyOutcome.NONE):
            _assert_new(paths, old_key)
        else:
            assert outcome is ApplyOutcome.FAILED, f"crash after step {crash_after}: {outcome}"
            _assert_old(paths, old_key)
        assert not (_restore_root(paths) / "journal.json").exists()
        assert apply_staged(paths, ok_migrate) is ApplyOutcome.NONE
        outcomes.add(outcome)

    assert ApplyOutcome.APPLIED in outcomes and ApplyOutcome.FAILED in outcomes


def test_rollback_copy_restores_the_previous_install(target, archive_file):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)

    [rollback] = list_rollbacks(target)
    assert rollback["created_at"].endswith("Z")
    stage_rollback(target, rollback["id"])
    assert apply_staged(target, ok_migrate) is ApplyOutcome.APPLIED

    s = _state(target)
    assert s["hosts"] == ["source-host"]
    assert s["key"] == old_key
    assert s["web_env"] == "A=old\n"
    assert "api:old" in s["api"]


def test_rollback_directories_are_private(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)
    [rollback] = list_rollbacks(target)
    rollback_dir = _restore_root(target) / f"rollback-{rollback['id']}"
    assert stat.S_IMODE(rollback_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(_restore_root(target).stat().st_mode) == 0o700
    assert stat.S_IMODE((target.stacks_dir / ".dockmon-restore").stat().st_mode) == 0o700


def test_only_the_newest_rollback_is_kept(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)
    [first] = list_rollbacks(target)

    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)

    [second] = list_rollbacks(target)
    assert second["id"] != first["id"]
    assert not (target.stacks_dir / ".dockmon-restore" / f"rollback-{first['id']}").exists()


def test_delete_rollback(target, archive_file):
    stage_archive(target, archive_file, PASSPHRASE)
    apply_staged(target, ok_migrate)
    [rollback] = list_rollbacks(target)

    delete_rollback(target, rollback["id"])

    assert list_rollbacks(target) == []
    assert not (target.stacks_dir / ".dockmon-restore" / f"rollback-{rollback['id']}").exists()


@pytest.mark.parametrize("bad_id", ["../../etc", "x/y", "", "20260925T000000Z/.."])
def test_rollback_ids_are_validated(target, bad_id):
    with pytest.raises(BackupError):
        delete_rollback(target, bad_id)
    with pytest.raises(BackupError):
        stage_rollback(target, bad_id)


def test_stack_dir_on_another_filesystem_fails_before_the_swap(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    real_device = restore._device_of

    def fake_device(path: Path) -> int:
        if path == target.stacks_dir / "api":
            return -1
        return real_device(path)

    monkeypatch.setattr(restore, "_device_of", fake_device)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    _assert_old(target, old_key)


def test_verify_checks_without_staging(target, archive_file):
    manifest = verify_archive(target, archive_file, PASSPHRASE)

    assert manifest["summary"]["hosts"] == 1
    assert pending_manifest(target) is None
    with pytest.raises(BackupDecryptError):
        verify_archive(target, archive_file, "wrong passphrase!!")


def test_live_directory_in_place_of_an_archived_file_is_never_moved(target, archive_file):
    old_key = target.key_path.read_bytes()
    env = target.stacks_dir / "web" / "app.env"
    env.unlink()
    env.mkdir()
    (env / "bind-data").write_text("precious")
    stage_archive(target, archive_file, PASSPHRASE)

    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED

    assert (env / "bind-data").read_text() == "precious"
    assert target.key_path.read_bytes() == old_key


def test_symlinked_stack_directory_is_refused(target, archive_file, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(target.stacks_dir / "api")
    os.symlink(outside, target.stacks_dir / "api")
    stage_archive(target, archive_file, PASSPHRASE)

    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    assert list(outside.iterdir()) == []


def test_live_managed_files_missing_from_the_backup_are_parked(target, archive_file):
    api = target.stacks_dir / "api"
    (api / "compose.yaml").write_text("services:\n  api:\n    image: api:stale\n")
    (api / ".env").write_text("STALE=1\n")
    stage_archive(target, archive_file, PASSPHRASE)

    apply_staged(target, ok_migrate)

    assert not (api / "compose.yaml").exists()
    assert not (api / ".env").exists()
    assert "api:new" in (api / "docker-compose.yml").read_text()


def test_rollback_restores_parked_extra_files_and_removes_created_stack_dirs(target, archive_file, monkeypatch):
    api = target.stacks_dir / "api"
    (api / "compose.yaml").write_text("services: {}\n")
    stage_archive(target, archive_file, PASSPHRASE)
    real_move = restore._move
    calls = []

    def fail_late(src, dst):
        calls.append(1)
        if len(calls) == 12:
            raise OSError("I/O error")
        real_move(src, dst)

    monkeypatch.setattr(restore, "_move", fail_late)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED

    assert (api / "compose.yaml").read_text() == "services: {}\n"
    assert not (target.stacks_dir / "worker").exists()


def test_rollback_never_moves_an_original_whose_staged_copy_was_lost(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)

    def lose_staged_then_fail(plan):
        for entry in plan["items"]:
            if entry["live"] == str(target.key_path):
                os.unlink(entry["staged"])
        raise OSError("power blip")

    monkeypatch.setattr(restore, "_swap", lose_staged_then_fail)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    assert target.key_path.read_bytes() == old_key


def test_failed_journal_write_fails_the_restore_without_blocking_start(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    real_write = restore._write_json_atomic

    def no_space_for_journal(path, data):
        if path == target.journal_path:
            raise OSError(28, "No space left on device")
        real_write(path, data)

    monkeypatch.setattr(restore, "_write_json_atomic", no_space_for_journal)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    monkeypatch.undo()

    _assert_old(target, old_key)
    assert pending_manifest(target) is None
    assert apply_staged(target, ok_migrate) is ApplyOutcome.NONE


def test_post_commit_cleanup_failure_does_not_block_start(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    real_remove = restore._remove

    def certs_stuck(path):
        if path == target.certs_dir:
            raise OSError("device busy")
        real_remove(path)

    monkeypatch.setattr(restore, "_remove", certs_stuck)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.APPLIED
    _assert_new(target, old_key)
    assert not (_restore_root(target) / "journal.json").exists()


def test_verify_leaves_other_upload_workspaces_alone(target, archive_file):
    other = target.data_dir / ".dockmon-restore" / "upload" / "in-flight"
    other.mkdir(parents=True)

    verify_archive(target, archive_file, PASSPHRASE)

    assert other.exists()
    apply_staged(target, ok_migrate)
    assert not other.exists()


def test_cleanup_failure_after_rollback_does_not_block_start(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    monkeypatch.setattr(restore, "_swap", lambda plan: (_ for _ in ()).throw(OSError("I/O error")))
    monkeypatch.setattr(restore, "_fail_pending", lambda paths: (_ for _ in ()).throw(OSError("still busy")))

    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    _assert_old(target, old_key)
    monkeypatch.undo()

    assert apply_staged(target, ok_migrate) is ApplyOutcome.FAILED
    assert pending_manifest(target) is None
    assert apply_staged(target, ok_migrate) is ApplyOutcome.NONE


def test_pending_removal_failure_after_commit_does_not_block_start_or_reapply(target, archive_file, monkeypatch):
    old_key = target.key_path.read_bytes()
    stage_archive(target, archive_file, PASSPHRASE)
    real_remove = restore._remove

    def pending_stuck(path):
        if path == target.pending_dir:
            raise OSError("device busy")
        real_remove(path)

    monkeypatch.setattr(restore, "_remove", pending_stuck)
    assert apply_staged(target, ok_migrate) is ApplyOutcome.APPLIED
    assert (_restore_root(target) / "journal.json").exists()
    monkeypatch.undo()

    (target.stacks_dir / "web" / ".env").write_text("A=edited-after-restore\n")
    assert apply_staged(target, ok_migrate) is ApplyOutcome.APPLIED
    assert (target.stacks_dir / "web" / ".env").read_text() == "A=edited-after-restore\n"
    assert pending_manifest(target) is None
    assert apply_staged(target, ok_migrate) is ApplyOutcome.NONE
    assert host_names(target.db_path) == ["backup-host"]
    assert target.key_path.read_bytes() != old_key
