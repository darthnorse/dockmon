"""Tests for env-file name safety and env_file: directive parsing (#205)."""
import pytest

from utils.env_files import is_safe_env_filename, parse_env_file_refs, is_env_filename, parse_bind_mount_sources, MAX_ENV_FILE_BYTES


@pytest.mark.parametrize("name", [".env", ".db.env", "app.env", "./app.env"])
def test_is_safe_env_filename_accepts_bare_same_dir(name):
    assert is_safe_env_filename(name) is True


@pytest.mark.parametrize("name", [
    "", "/etc/passwd", "../secrets.env", "sub/app.env", "..", ".",
    "a\\b.env", "x/../y.env",
])
def test_is_safe_env_filename_rejects_unsafe(name):
    assert is_safe_env_filename(name) is False


@pytest.mark.parametrize("name", [" .env", ".env ", "\t.env", " ", "./ ", "  "])
def test_is_safe_env_filename_rejects_whitespace(name):
    """Whitespace-padded and whitespace-only names must be rejected.

    The stored filename strips only a leading './', not whitespace, so
    accepting padded names would create a mismatch between the validated
    form and what is written to disk.
    """
    assert is_safe_env_filename(name) is False


@pytest.mark.parametrize("name", [".env", ".db.env", "app.env", "./app.env"])
def test_is_safe_env_filename_whitespace_regression_still_accepts_clean(name):
    """Clean names (no surrounding whitespace) must still pass after the
    whitespace rejection change."""
    assert is_safe_env_filename(name) is True


def test_parse_string_list_and_longform():
    compose = """
services:
  app:
    image: x
    env_file: .app.env
  db:
    image: y
    env_file:
      - .db.env
      - path: ./extra.env
        required: false
"""
    captured, skipped = parse_env_file_refs(compose)
    assert captured == [".app.env", ".db.env", "extra.env"]
    assert skipped == []


def test_parse_skips_out_of_dir_refs():
    compose = """
services:
  app:
    image: x
    env_file:
      - .ok.env
      - ../escape.env
      - /abs/secret.env
      - conf/sub.env
"""
    captured, skipped = parse_env_file_refs(compose)
    assert captured == [".ok.env"]
    assert sorted(skipped) == ["../escape.env", "/abs/secret.env", "conf/sub.env"]


def test_parse_malformed_or_no_services_returns_empty():
    assert parse_env_file_refs(":\n  bad: [") == ([], [])
    assert parse_env_file_refs("version: '3'") == ([], [])


@pytest.mark.parametrize("name", [
    ".env", ".env.prod", ".env.staging", ".db.env", "prod.env", "app.env",
])
def test_is_env_filename_accepts_env_naming(name):
    assert is_env_filename(name) is True


@pytest.mark.parametrize("name", [
    ".envrc", "env", "compose.yaml", "docker-compose.yml", "data.txt", "config", "",
])
def test_is_env_filename_rejects_non_env(name):
    assert is_env_filename(name) is False


def test_parse_deeply_nested_yaml_does_not_raise():
    # A deeply-nested document makes PyYAML's safe_load raise RecursionError
    # (well under any size cap). The parser must swallow it and report no env
    # files instead of letting the exception escape to the caller (500).
    nested = "a: " + "[" * 20000 + "]" * 20000 + "\n"
    assert parse_env_file_refs(nested) == ([], [])


def test_parse_bind_mount_sources_short_and_long():
    compose = """
services:
  app:
    image: x
    volumes:
      - ./data.env:/app/data.env
      - .secret.env:/run/secret.env:ro
      - type: bind
        source: ./conf.env
        target: /etc/conf.env
"""
    assert parse_bind_mount_sources(compose) == {"data.env", ".secret.env", "conf.env"}


def test_parse_bind_mount_sources_ignores_abs_subdir_and_named_volume():
    # Absolute and subdir sources point outside the stack dir's top level (no
    # discovered file can collide), and a long-form named volume has no path.
    compose = """
services:
  app:
    image: x
    volumes:
      - /etc/host.env:/x
      - ./sub/dir.env:/y
      - type: volume
        source: dbdata
        target: /data
"""
    assert parse_bind_mount_sources(compose) == set()


def test_parse_bind_mount_sources_captures_var_prefixed_same_dir():
    # ${PWD}/x and $HOME/x resolve to a same-dir file; the bare name must be
    # excluded from discovery so the bind-mounted data file isn't surfaced.
    compose = """
services:
  app:
    image: x
    volumes:
      - ${PWD}/secret.env:/run/secret.env
      - $HOME/app.env:/app/app.env
"""
    assert parse_bind_mount_sources(compose) == {"secret.env", "app.env"}


def test_parse_bind_mount_sources_captures_toplevel_local_bind_device():
    # A named volume that is really a local bind to a same-dir file.
    compose = """
services:
  app:
    image: x
    volumes:
      - runtime:/data
volumes:
  runtime:
    driver_opts:
      type: none
      o: bind
      device: ./runtime.env
"""
    assert "runtime.env" in parse_bind_mount_sources(compose)


def test_parse_bind_mount_sources_malformed_returns_empty_set():
    assert parse_bind_mount_sources(": : not yaml : :") == set()
    assert parse_bind_mount_sources("[]") == set()


def test_max_env_file_bytes_is_one_mib():
    assert MAX_ENV_FILE_BYTES == 1024 * 1024
