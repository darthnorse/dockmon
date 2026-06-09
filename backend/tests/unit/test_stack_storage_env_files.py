"""Round-trip + safety tests for multi-env-file stack storage."""
import pytest

from deployment import stack_storage


@pytest.fixture
def stacks_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(stack_storage, "STACKS_DIR", tmp_path)
    return tmp_path


async def test_write_then_read_roundtrips_all_files(stacks_dir):
    compose = "services:\n  db:\n    image: x\n    env_file:\n      - .db.env\n"
    env_files = {".env": "TOP=1\n", ".db.env": "PASSWORD=secret\n"}
    await stack_storage.write_stack("myapp", compose, env_files, create_only=True)

    read_compose, read_env = await stack_storage.read_stack("myapp")
    assert read_compose == compose
    assert read_env == env_files


async def test_write_rejects_unsafe_filename(stacks_dir):
    with pytest.raises(ValueError):
        await stack_storage.write_stack(
            "myapp", "services: {}\n", {"../escape.env": "X=1\n"}
        )


async def test_write_does_not_delete_other_files(stacks_dir):
    # Pre-existing bind-mount data + an orphan env file must survive a write.
    await stack_storage.write_stack("myapp", "services: {}\n", {".env": "A=1\n"}, create_only=True)
    data_dir = stacks_dir / "myapp" / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("BINARY")

    await stack_storage.write_stack("myapp", "services: {}\n", {".env": "A=2\n"})
    assert (data_dir / "db.sqlite").read_text() == "BINARY"


async def test_referenced_but_missing_file_reads_as_empty(stacks_dir):
    # compose references .db.env but the file does not exist yet.
    compose = "services:\n  db:\n    image: x\n    env_file: .db.env\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    _compose, env = await stack_storage.read_stack("myapp")
    assert env == {".db.env": ""}


async def test_compose_referencing_dot_env_yields_single_key(stacks_dir):
    # A compose that names .env via env_file: must still produce exactly one
    # ".env" entry with the on-disk content (no duplicate read/clobber).
    compose = "services:\n  app:\n    image: x\n    env_file: .env\n"
    await stack_storage.write_stack("myapp", compose, {".env": "A=1\n"}, create_only=True)
    _compose, env = await stack_storage.read_stack("myapp")
    assert env == {".env": "A=1\n"}


async def test_no_env_and_no_refs_returns_empty_map(stacks_dir):
    # No .env on disk and no env_file: directives -> empty map.
    compose = "services:\n  app:\n    image: x\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    _compose, env = await stack_storage.read_stack("myapp")
    assert env == {}


async def test_symlinked_env_file_not_read(stacks_dir, tmp_path):
    """A referenced env file replaced by a symlink to outside content must not be read."""
    compose = "services:\n  db:\n    image: x\n    env_file:\n      - .secret.env\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)

    # Replace the (missing) referenced file with a symlink to an outside file
    outside = tmp_path / "outside.env"
    outside.write_text("LEAKED=yes\n")
    symlink_path = stacks_dir / "myapp" / ".secret.env"
    symlink_path.symlink_to(outside)

    _compose, env = await stack_storage.read_stack("myapp")
    assert ".secret.env" not in env, "Symlinked env file must not appear in env map"
    assert "LEAKED=yes" not in str(env), "Symlink target content must not leak"


def test_referenced_env_filenames_is_dot_env_plus_refs_minus_compose():
    compose = (
        "services:\n"
        "  app:\n"
        "    image: x\n"
        "    env_file:\n"
        "      - .db.env\n"
        "      - compose.yaml\n"   # a compose filename ref must never be managed
    )
    assert stack_storage.referenced_env_filenames(compose) == {".env", ".db.env"}


def test_referenced_env_filenames_no_refs_is_just_dot_env():
    assert stack_storage.referenced_env_filenames("services:\n  app:\n    image: x\n") == {".env"}
