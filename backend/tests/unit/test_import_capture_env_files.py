import os

import pytest

from deployment.routes import _read_local_file, ReadComposeFileRequest, MAX_ENV_FILE_SIZE


async def test_read_local_file_captures_referenced_env_files(tmp_path):
    # tmp_path resolves under /tmp, which _is_path_safe does not block.
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  db:\n    image: x\n    env_file:\n      - .db.env\n      - ../escape.env\n")
    (tmp_path / ".env").write_text("TOP=1\n")
    (tmp_path / ".db.env").write_text("P=secret\n")

    resp = await _read_local_file(ReadComposeFileRequest(path=str(compose)))
    assert resp.success
    assert resp.env_files == {".env": "TOP=1\n", ".db.env": "P=secret\n"}
    assert resp.skipped_env_files == ["../escape.env"]
    # Legacy single-.env field stays populated for back-compat during migration.
    assert resp.env_content == "TOP=1\n"


async def test_read_local_file_skips_symlinked_env_file(tmp_path):
    """A referenced env file that is a symlink must not be read; its name must be in skipped."""
    outside = tmp_path.parent / "outside_secret.env"
    outside.write_text("SECRET=leaked\n")

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  db:\n    image: x\n    env_file:\n      - .secret.env\n"
    )
    symlink_path = tmp_path / ".secret.env"
    symlink_path.symlink_to(outside)

    resp = await _read_local_file(ReadComposeFileRequest(path=str(compose)))
    assert resp.success
    assert ".secret.env" not in resp.env_files, "Symlinked env file must not be read"
    assert "SECRET=leaked" not in str(resp.env_files), "Symlink target content must not appear"
    assert ".secret.env" in resp.skipped_env_files, "Symlinked file name must be in skipped"


async def test_read_local_file_skips_oversized_env_file(tmp_path):
    """An env file just over MAX_ENV_FILE_SIZE must be skipped, not read."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  db:\n    image: x\n    env_file:\n      - .big.env\n"
    )
    big_env = tmp_path / ".big.env"
    big_env.write_bytes(b"X=1\n" * ((MAX_ENV_FILE_SIZE // 4) + 1))  # just over 1 MB

    resp = await _read_local_file(ReadComposeFileRequest(path=str(compose)))
    assert resp.success
    assert ".big.env" not in resp.env_files, "Oversized env file must not be read"
    assert ".big.env" in resp.skipped_env_files, "Oversized env file name must be in skipped"
