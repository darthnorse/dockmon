"""Tests for env-file name safety and env_file: directive parsing (#205)."""
import pytest

from utils.env_files import is_safe_env_filename, parse_env_file_refs


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
