"""install-agent.sh carries proxy env vars into the systemd EnvironmentFile."""

import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install-agent.sh"


def _function_source():
    match = re.search(r"^proxy_env_lines\(\) \{\n.*?^\}\n", SCRIPT.read_text(), re.S | re.M)
    assert match, "proxy_env_lines() not found in install-agent.sh"
    return match.group(0)


def _run(env):
    harness = 'log_error() { echo "ERR: $1" >&2; }\n' + _function_source() + "proxy_env_lines\n"
    return subprocess.run(["bash", "-c", harness], env={"PATH": "/usr/bin:/bin", **env},
                          capture_output=True, text=True)


def test_no_proxy_vars_writes_nothing():
    result = _run({})
    assert result.returncode == 0
    assert result.stdout == ""


def test_upper_and_lowercase_vars_are_passed_through():
    env = {
        "HTTP_PROXY": "http://proxy.lan:3128",
        "HTTPS_PROXY": "http://user:p%40ss@proxy.lan:3128",
        "NO_PROXY": "localhost,127.0.0.1,.lan",
        "http_proxy": "http://proxy.lan:3128",
        "no_proxy": "localhost",
    }
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert sorted(result.stdout.splitlines()) == sorted(f"{k}={v}" for k, v in env.items())


def test_empty_var_is_skipped():
    result = _run({"HTTPS_PROXY": ""})
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("value", [
    "http://proxy:3128\nREGISTRATION_TOKEN=evil",
    "http://proxy:3128\r",
    'http://pro"xy:3128',
    "http://pro\\xy:3128",
])
def test_injection_characters_are_rejected(value):
    result = _run({"HTTPS_PROXY": value})
    assert result.returncode != 0
    assert "HTTPS_PROXY" in result.stderr
    assert result.stdout == ""
