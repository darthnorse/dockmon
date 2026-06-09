from deployment.routes import _read_local_file, ReadComposeFileRequest


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
