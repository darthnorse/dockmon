"""
Tests for env_files handling in AgentDeploymentExecutor:
- agent_supports_multi_env_files capability check
- env_files shipped in command payload
- multi-env-file deploys blocked on old agents
"""
import json
from unittest.mock import MagicMock

from deployment import agent_executor as ae


def _agent(capabilities: dict):
    a = MagicMock()
    a.capabilities = json.dumps(capabilities)
    return a


def test_agent_supports_multi_env_files_true_false():
    assert ae.agent_supports_multi_env_files(_agent({"multi_env_files": True})) is True
    assert ae.agent_supports_multi_env_files(_agent({"stats_collection": True})) is False
    assert ae.agent_supports_multi_env_files(None) is False


def test_agent_supports_multi_env_files_dict_capabilities():
    """Agent with capabilities as dict (already parsed JSON) also works."""
    agent = MagicMock()
    agent.capabilities = {"multi_env_files": True}
    assert ae.agent_supports_multi_env_files(agent) is True


def test_agent_supports_multi_env_files_invalid_json():
    """Agent with invalid JSON capabilities returns False."""
    agent = MagicMock()
    agent.capabilities = "not-valid-json"
    assert ae.agent_supports_multi_env_files(agent) is False


def test_agent_supports_multi_env_files_false_value():
    """Agent with multi_env_files=False returns False."""
    assert ae.agent_supports_multi_env_files(_agent({"multi_env_files": False})) is False
