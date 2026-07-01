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


async def test_discovered_env_filenames_surfaces_unreferenced_only(stacks_dir):
    # Compose references .db.env and bind-mounts a data file named bind.env.
    compose = (
        "services:\n"
        "  app:\n"
        "    image: x\n"
        "    env_file:\n"
        "      - .db.env\n"
        "    volumes:\n"
        "      - ./bind.env:/etc/bind.env\n"
    )
    stack_dir = stacks_dir / "myapp"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(compose)
    (stack_dir / ".env").write_text("A=1\n")            # referenced (.env) -> excluded
    (stack_dir / ".db.env").write_text("P=2\n")          # env_file: ref -> excluded
    (stack_dir / ".env.staging").write_text("S=3\n")     # unreferenced -> DISCOVERED
    (stack_dir / "prod.env").write_text("Q=4\n")         # unreferenced -> DISCOVERED
    (stack_dir / "bind.env").write_text("DATA\n")        # bind-mount source -> excluded
    (stack_dir / "notes.txt").write_text("hello\n")      # not env-named -> excluded
    sub = stack_dir / "sub"
    sub.mkdir()
    (sub / "nested.env").write_text("N=1\n")             # subdir -> not enumerated

    result = stack_storage._discovered_env_filenames(stack_dir, compose)
    assert result == {".env.staging", "prod.env"}


async def test_discovered_env_filenames_excludes_symlink_and_oversized(stacks_dir, tmp_path):
    from utils.env_files import MAX_ENV_FILE_BYTES

    compose = "services:\n  app:\n    image: x\n"
    stack_dir = stacks_dir / "myapp"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(compose)

    outside = tmp_path / "outside.env"
    outside.write_text("LEAK=1\n")
    (stack_dir / "link.env").symlink_to(outside)         # symlink -> excluded
    (stack_dir / "big.env").write_text("X" * (MAX_ENV_FILE_BYTES + 1))  # too big -> excluded
    (stack_dir / ".env.ok").write_text("OK=1\n")         # discovered

    result = stack_storage._discovered_env_filenames(stack_dir, compose)
    assert result == {".env.ok"}


async def test_discovered_env_filenames_excludes_directory_and_fifo(stacks_dir):
    import os as _os
    compose = "services:\n  app:\n    image: x\n"
    stack_dir = stacks_dir / "myapp"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(compose)
    (stack_dir / "config.env").mkdir()                  # directory named like an env file -> excluded
    _os.mkfifo(stack_dir / "pipe.env")                  # FIFO -> excluded (non-regular file)
    (stack_dir / ".env.real").write_text("R=1\n")       # regular env file -> discovered

    result = stack_storage._discovered_env_filenames(stack_dir, compose)
    assert result == {".env.real"}


async def test_discovered_env_filenames_handles_unparseable_compose(stacks_dir):
    # Malformed compose: referenced/bind-source parsing must not throw; discovery
    # still surfaces an env-named on-disk file.
    compose = ": : not valid yaml : :"
    stack_dir = stacks_dir / "myapp"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(compose)
    (stack_dir / ".env.staging").write_text("S=1\n")

    result = stack_storage._discovered_env_filenames(stack_dir, compose)
    assert result == {".env.staging"}


async def test_delete_env_file_removes_discovered_unreferenced(stacks_dir):
    # An unreferenced, env-named file is now deletable (delete follows visibility).
    compose = "services:\n  app:\n    image: x\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    staging = stacks_dir / "myapp" / ".env.staging"
    staging.write_text("S=1\n")

    deleted = await stack_storage.delete_env_file("myapp", ".env.staging")
    assert deleted is True
    assert not staging.exists()


async def test_delete_env_file_refuses_bind_mounted_data(stacks_dir):
    # A *.env file the compose bind-mounts is data, not a managed env file.
    compose = (
        "services:\n"
        "  app:\n"
        "    image: x\n"
        "    volumes:\n"
        "      - ./bind.env:/etc/bind.env\n"
    )
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    bind = stacks_dir / "myapp" / "bind.env"
    bind.write_text("DATA\n")

    deleted = await stack_storage.delete_env_file("myapp", "bind.env")
    assert deleted is False
    assert bind.read_text() == "DATA\n"


async def test_delete_env_file_refuses_compose_file(stacks_dir):
    compose = "services:\n  app:\n    image: x\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    deleted = await stack_storage.delete_env_file("myapp", "compose.yaml")
    assert deleted is False
    assert (stacks_dir / "myapp" / "compose.yaml").exists()


async def test_read_stack_surfaces_unreferenced_env_files(stacks_dir):
    compose = "services:\n  app:\n    image: x\n    env_file:\n      - .env.dev\n"
    await stack_storage.write_stack("myapp", compose, {".env.dev": "D=1\n"}, create_only=True)
    # Add two unreferenced env files directly on disk (the env-swap orphans).
    (stacks_dir / "myapp" / ".env.staging").write_text("S=2\n")
    (stacks_dir / "myapp" / ".env.prod").write_text("P=3\n")

    _compose, env = await stack_storage.read_stack("myapp")
    assert env == {".env.dev": "D=1\n", ".env.staging": "S=2\n", ".env.prod": "P=3\n"}


async def test_read_stack_omits_dot_env_when_absent(stacks_dir):
    # Regression: with no .env on disk and no refs, read_stack must NOT emit a
    # ".env" key (keeps the editor's default .env tab virtual; a save then never
    # writes an empty .env file).
    compose = "services:\n  app:\n    image: x\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    (stacks_dir / "myapp" / ".env.staging").write_text("S=1\n")

    _compose, env = await stack_storage.read_stack("myapp")
    assert ".env" not in env
    assert env == {".env.staging": "S=1\n"}


async def test_read_stack_keeps_referenced_file_even_if_bind_mounted(stacks_dir):
    # "Authoritative wins": a file that is BOTH env_file:-referenced and
    # bind-mounted must still surface (the explicit reference proves it's env).
    compose = (
        "services:\n"
        "  app:\n"
        "    image: x\n"
        "    env_file:\n"
        "      - .shared.env\n"
        "    volumes:\n"
        "      - ./.shared.env:/etc/app/.shared.env\n"
    )
    await stack_storage.write_stack("myapp", compose, {".shared.env": "K=1\n"}, create_only=True)
    _compose, env = await stack_storage.read_stack("myapp")
    assert env.get(".shared.env") == "K=1\n"


async def test_managed_set_is_superset_of_read_tabs_and_includes_discovered(stacks_dir):
    # Lockstep: every editor tab is in the delete allowlist, and a discovered
    # file is deletable.
    compose = "services:\n  app:\n    image: x\n    env_file:\n      - .db.env\n"
    await stack_storage.write_stack(
        "myapp", compose, {".env": "A=1\n", ".db.env": "P=2\n"}, create_only=True
    )
    stack_path = stacks_dir / "myapp"
    (stack_path / ".env.staging").write_text("S=3\n")

    managed = stack_storage._managed_env_filenames(stack_path, compose)
    _compose, env = await stack_storage.read_stack("myapp")
    assert set(env.keys()) <= managed
    assert ".env.staging" in managed


async def test_read_stack_include_discovered_false_excludes_unreferenced(stacks_dir):
    # Deploy reads (include_discovered=False) must NOT surface env-swap orphans,
    # so inactive env files aren't shipped to remote agents / don't trip the
    # old-agent multi_env_files gate. The editor read (default) still shows them.
    compose = "services:\n  app:\n    image: x\n    env_file:\n      - .env.dev\n"
    await stack_storage.write_stack("myapp", compose, {".env.dev": "D=1\n"}, create_only=True)
    (stacks_dir / "myapp" / ".env.staging").write_text("S=2\n")  # discovered orphan

    _c, editor_env = await stack_storage.read_stack("myapp")  # default include_discovered=True
    assert ".env.staging" in editor_env

    _c2, deploy_env = await stack_storage.read_stack("myapp", include_discovered=False)
    assert deploy_env == {".env.dev": "D=1\n"}
    assert ".env.staging" not in deploy_env


async def test_var_prefixed_bind_mount_data_not_surfaced_or_deletable(stacks_dir):
    # A same-dir env file bind-mounted via ${PWD} is data, not a managed env
    # file: it must not be discovered as a tab nor deletable, while a genuine
    # env-swap orphan alongside it still is.
    compose = (
        "services:\n  app:\n    image: x\n"
        "    volumes:\n      - ${PWD}/secret.env:/run/secret.env\n"
    )
    stack_dir = stacks_dir / "myapp"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(compose)
    (stack_dir / "secret.env").write_text("DATA\n")     # bind-mounted -> hidden
    (stack_dir / ".env.staging").write_text("S=1\n")    # genuine discovered env

    assert stack_storage._discovered_env_filenames(stack_dir, compose) == {".env.staging"}
    assert await stack_storage.delete_env_file("myapp", "secret.env") is False
    assert (stack_dir / "secret.env").read_text() == "DATA\n"


async def test_read_stack_reskips_oversized_discovered_file(stacks_dir, monkeypatch):
    # Simulate a scan->grow race: discovery 'returned' big.env, but at read time
    # it exceeds the cap. read_stack must re-check size and skip it (not slurp it).
    from utils.env_files import MAX_ENV_FILE_BYTES

    compose = "services:\n  app:\n    image: x\n"
    await stack_storage.write_stack("myapp", compose, {}, create_only=True)
    (stacks_dir / "myapp" / "big.env").write_text("X" * (MAX_ENV_FILE_BYTES + 1))
    monkeypatch.setattr(stack_storage, "_discovered_env_filenames", lambda sp, cy: {"big.env"})

    _compose, env = await stack_storage.read_stack("myapp")
    assert "big.env" not in env
