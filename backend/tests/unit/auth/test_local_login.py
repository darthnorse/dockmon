"""
Unit tests for the SSO-only (disable local login) effective-state helper.

The effective disabled state is the DB flag AND NOT the env override:
    DOCKMON_FORCE_LOCAL_LOGIN=true is a break-glass that forces local login on
    regardless of what the database says.
"""

import pytest

from auth.local_login import local_login_effective_disabled
from config.settings import AppConfig


def test_disabled_when_db_flag_set_and_no_override(monkeypatch):
    """DB flag on + no env override => local login is effectively disabled."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)
    assert local_login_effective_disabled(True) is True


def test_env_override_forces_local_login_on(monkeypatch):
    """The env override wins over the DB flag (break-glass)."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    assert local_login_effective_disabled(True) is False


def test_not_disabled_when_db_flag_unset(monkeypatch):
    """DB flag off => local login stays enabled."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)
    assert local_login_effective_disabled(False) is False
