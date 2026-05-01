"""Tests for URL template resolver (Issue #207 — webui_url_mapping_chain)."""
from utils.url_template import resolve_url_template, resolve_chain


class TestResolveTemplate:
    def test_substitutes_env_placeholder(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com"},
            labels={},
        )
        assert result == "https://app.example.com"

    def test_substitutes_label_placeholder(self):
        result = resolve_url_template(
            "${label:com.acme.url}",
            env={},
            labels={"com.acme.url": "https://app.example.com"},
        )
        assert result == "https://app.example.com"

    def test_substitutes_multiple_placeholders(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}:${env:VIRTUAL_PORT}",
            env={"VIRTUAL_HOST": "app.example.com", "VIRTUAL_PORT": "8443"},
            labels={},
        )
        assert result == "https://app.example.com:8443"

    def test_missing_env_returns_none(self):
        result = resolve_url_template(
            "https://${env:NOT_SET}",
            env={"OTHER": "x"},
            labels={},
        )
        assert result is None

    def test_missing_label_returns_none(self):
        result = resolve_url_template(
            "${label:com.acme.url}",
            env={},
            labels={"other": "x"},
        )
        assert result is None

    def test_partial_missing_returns_none(self):
        # If ANY placeholder is missing, the whole template fails.
        result = resolve_url_template(
            "https://${env:HOST}:${env:PORT}",
            env={"HOST": "x"},
            labels={},
        )
        assert result is None

    def test_empty_value_returns_none(self):
        # An env var set to empty string is treated as missing.
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": ""},
            labels={},
        )
        assert result is None

    def test_no_placeholders_returns_template_verbatim(self):
        result = resolve_url_template(
            "https://hardcoded.example.com",
            env={},
            labels={},
        )
        assert result == "https://hardcoded.example.com"

    def test_handles_none_env_and_labels(self):
        result = resolve_url_template(
            "https://${env:X}",
            env=None,
            labels=None,
        )
        assert result is None


class TestResolveChain:
    def test_first_match_wins(self):
        result = resolve_chain(
            ["https://${env:WEBUI_URL}", "https://${env:VIRTUAL_HOST}"],
            env={"WEBUI_URL": "primary.example.com", "VIRTUAL_HOST": "fallback.example.com"},
            labels={},
        )
        assert result == "https://primary.example.com"

    def test_falls_through_to_next(self):
        result = resolve_chain(
            ["https://${env:WEBUI_URL}", "https://${env:VIRTUAL_HOST}"],
            env={"VIRTUAL_HOST": "fallback.example.com"},
            labels={},
        )
        assert result == "https://fallback.example.com"

    def test_all_empty_returns_none(self):
        result = resolve_chain(
            ["https://${env:A}", "https://${env:B}"],
            env={},
            labels={},
        )
        assert result is None

    def test_empty_chain_returns_none(self):
        assert resolve_chain([], env={"A": "x"}, labels={}) is None

    def test_none_chain_returns_none(self):
        assert resolve_chain(None, env={"A": "x"}, labels={}) is None
