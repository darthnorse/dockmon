import stat

import pytest

import manage_backup
from backup import restore
from backup.errors import RestoreStateError
from tests.unit.backup.conftest import FAST_KDF, PASSPHRASE, build_install, host_names


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(manage_backup, "BACKUP_KDF", FAST_KDF)


@pytest.fixture
def passphrase_file(tmp_path):
    path = tmp_path / "passphrase"
    path.write_text(PASSPHRASE + "\n")
    return path


def _run(paths, *argv) -> int:
    return manage_backup.main(list(argv), paths=paths)


def test_create_writes_a_private_archive(install, tmp_path, passphrase_file, capsys):
    out = tmp_path / "out.dmbak"

    assert _run(install, "create", str(out), "--passphrase-file", str(passphrase_file)) == 0

    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert "1 hosts" in capsys.readouterr().out
    assert not (tmp_path / "out.dmbak.partial").exists()


def test_create_refuses_to_overwrite(install, tmp_path, passphrase_file):
    out = tmp_path / "out.dmbak"
    out.write_text("keep me")

    assert _run(install, "create", str(out), "--passphrase-file", str(passphrase_file)) == 1
    assert out.read_text() == "keep me"


def test_create_without_passphrase_source_fails_non_interactively(install, tmp_path, monkeypatch):
    monkeypatch.setattr(manage_backup.sys.stdin, "isatty", lambda: False)
    assert _run(install, "create", str(tmp_path / "out.dmbak")) == 1
    assert not (tmp_path / "out.dmbak").exists()


def test_verify_accepts_a_good_archive_and_rejects_a_wrong_passphrase(install, tmp_path, passphrase_file, capsys):
    out = tmp_path / "out.dmbak"
    _run(install, "create", str(out), "--passphrase-file", str(passphrase_file))

    assert _run(install, "verify", str(out), "--passphrase-file", str(passphrase_file)) == 0
    assert "OK" in capsys.readouterr().out

    wrong = tmp_path / "wrong"
    wrong.write_text("not the passphrase")
    assert _run(install, "verify", str(out), "--passphrase-file", str(wrong)) == 1
    assert "Wrong passphrase" in capsys.readouterr().err
    assert restore.pending_manifest(install) is None


def test_stage_then_apply_staged_restores(tmp_path, head_db_template, install, passphrase_file):
    source = build_install(tmp_path / "other", head_db_template, "backup-host", "new")
    out = tmp_path / "other.dmbak"
    assert _run(source, "create", str(out), "--passphrase-file", str(passphrase_file)) == 0

    assert _run(install, "stage", str(out), "--passphrase-file", str(passphrase_file)) == 0
    assert _run(install, "status") == 0
    assert _run(install, "apply-staged") == 0

    assert host_names(install.db_path) == ["backup-host"]
    assert _run(install, "apply-staged") == 0


def test_cancel(install, tmp_path, passphrase_file):
    out = tmp_path / "out.dmbak"
    _run(install, "create", str(out), "--passphrase-file", str(passphrase_file))
    _run(install, "stage", str(out), "--passphrase-file", str(passphrase_file))

    assert _run(install, "cancel") == 0
    assert restore.pending_manifest(install) is None


def test_apply_staged_exits_non_zero_when_rollback_failed(install, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RestoreStateError("journal kept")

    monkeypatch.setattr(manage_backup, "apply_staged", broken)
    assert _run(install, "apply-staged") == 1


def test_rollback_commands(tmp_path, head_db_template, install, passphrase_file, capsys):
    source = build_install(tmp_path / "other", head_db_template, "backup-host", "new")
    out = tmp_path / "other.dmbak"
    _run(source, "create", str(out), "--passphrase-file", str(passphrase_file))
    _run(install, "stage", str(out), "--passphrase-file", str(passphrase_file))
    _run(install, "apply-staged")
    capsys.readouterr()

    assert _run(install, "list-rollbacks") == 0
    [rollback] = restore.list_rollbacks(install)
    assert rollback["id"] in capsys.readouterr().out

    assert _run(install, "rollback", rollback["id"]) == 0
    assert _run(install, "apply-staged") == 0
    assert host_names(install.db_path) == ["source-host"]

    [newest] = restore.list_rollbacks(install)
    assert _run(install, "delete-rollback", newest["id"]) == 0
    assert restore.list_rollbacks(install) == []
    assert _run(install, "delete-rollback", "../../etc") == 1
