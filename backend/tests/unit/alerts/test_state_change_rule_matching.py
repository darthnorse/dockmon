"""
Unit tests for state-change alert rule matching (_rule_matches_event).

Covers:
- container_started: fires when a container transitions to running (issue #222,
  contributed via PR #223). Regression coverage for the integrated behavior.
- container_restarted: must fire on an actual restart cycle. Previously dead -
  the rule matched new_state == "restarting", which nothing ever emits (Docker
  'restart' surfaces as new_state == "running"). Now driven by the
  container_restarted flag set in the EventBus.
"""

import pytest
from unittest.mock import Mock

from alerts.engine import AlertEngine


def _rule(kind):
    rule = Mock()
    rule.kind = kind
    return rule


def _ctx(scope_type="container"):
    ctx = Mock()
    ctx.scope_type = scope_type
    return ctx


@pytest.fixture
def engine():
    return AlertEngine(db=Mock())


class TestContainerStartedMatching:
    """container_started fires on transition to running (start OR restart)."""

    def test_fires_on_running(self, engine):
        assert engine._rule_matches_event(
            _rule("container_started"), "state_change", _ctx(),
            {"new_state": "running"}
        ) is True

    def test_does_not_fire_on_stopped(self, engine):
        assert engine._rule_matches_event(
            _rule("container_started"), "state_change", _ctx(),
            {"new_state": "stopped"}
        ) is False

    def test_does_not_fire_on_non_state_change(self, engine):
        assert engine._rule_matches_event(
            _rule("container_started"), "action_taken", _ctx(),
            {"new_state": "running"}
        ) is False


class TestContainerRestartedMatching:
    """container_restarted fires on an actual restart cycle (flag-driven)."""

    def test_fires_on_restart_flag(self, engine):
        assert engine._rule_matches_event(
            _rule("container_restarted"), "state_change", _ctx(),
            {"new_state": "running", "container_restarted": True}
        ) is True

    def test_alias_container_restart_fires_on_flag(self, engine):
        assert engine._rule_matches_event(
            _rule("container_restart"), "state_change", _ctx(),
            {"new_state": "running", "container_restarted": True}
        ) is True

    def test_does_not_fire_on_plain_start(self, engine):
        # A plain start (no restart flag) must NOT trigger a restart rule
        assert engine._rule_matches_event(
            _rule("container_restarted"), "state_change", _ctx(),
            {"new_state": "running"}
        ) is False

    def test_does_not_fire_on_stopped(self, engine):
        # A stop event carries no restart flag, so a restart rule must not fire
        assert engine._rule_matches_event(
            _rule("container_restarted"), "state_change", _ctx(),
            {"new_state": "stopped"}
        ) is False
