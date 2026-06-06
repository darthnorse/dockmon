"""
Unit tests for notification default-template polish (container start/restart).

- _friendly_kind: maps raw alert kinds to human-readable titles.
- _get_default_template_v2: start/restart alerts use a template without the
  exit-code line (exit code is only meaningful for stop/crash events).
"""

import pytest
from unittest.mock import MagicMock

from notifications import NotificationService, _friendly_kind


class TestFriendlyKind:
    def test_started(self):
        assert _friendly_kind("container_started") == "Container Started"

    def test_restart_aliases_both_map_to_restarted(self):
        assert _friendly_kind("container_restart") == "Container Restarted"
        assert _friendly_kind("container_restarted") == "Container Restarted"

    def test_mapped_metric_kind(self):
        assert _friendly_kind("cpu_high") == "High CPU"

    def test_unmapped_kind_falls_back_to_title_case(self):
        assert _friendly_kind("some_new_kind") == "Some New Kind"

    def test_empty_or_none(self):
        assert _friendly_kind("") == ""
        assert _friendly_kind(None) == ""


class TestStartRestartDefaultTemplate:
    @pytest.fixture
    def svc(self):
        return NotificationService(db=MagicMock())

    def test_started_template_omits_exit_code(self, svc):
        tpl = svc._get_default_template_v2("container_started")
        assert "Exit code" not in tpl
        assert "{OLD_STATE}" in tpl and "{NEW_STATE}" in tpl

    def test_restarted_template_omits_exit_code(self, svc):
        assert "Exit code" not in svc._get_default_template_v2("container_restarted")
        assert "Exit code" not in svc._get_default_template_v2("container_restart")

    def test_paused_template_omits_exit_code(self, svc):
        # A paused container has not exited, so there is no exit code to show
        assert "Exit code" not in svc._get_default_template_v2("container_paused")

    def test_stopped_template_keeps_exit_code(self, svc):
        assert "Exit code" in svc._get_default_template_v2("container_stopped")

    def test_died_template_keeps_exit_code(self, svc):
        assert "Exit code" in svc._get_default_template_v2("container_died")
