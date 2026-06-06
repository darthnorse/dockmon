"""Tests for URL template resolver (Issue #207 — webui_url_mapping_chain)."""
from utils.url_template import (
    MAX_RESOLVED_URL_LENGTH,
    resolve_chain,
    resolve_url_template,
)


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


class TestResolverHardening:
    """Defensive checks on attacker-controlled placeholder values (Issue #207)."""

    def test_value_with_newline_returns_none(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com\nattacker.com"},
            labels={},
        )
        assert result is None

    def test_value_with_carriage_return_returns_none(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com\rattacker.com"},
            labels={},
        )
        assert result is None

    def test_value_with_tab_returns_none(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app\texample.com"},
            labels={},
        )
        assert result is None

    def test_value_with_null_byte_returns_none(self):
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com\x00"},
            labels={},
        )
        assert result is None

    def test_resolved_length_at_cap_passes(self):
        # Build a value that resolves to exactly MAX_RESOLVED_URL_LENGTH chars.
        prefix = "https://"
        value_len = MAX_RESOLVED_URL_LENGTH - len(prefix)
        result = resolve_url_template(
            "https://${env:HOST}",
            env={"HOST": "a" * value_len},
            labels={},
        )
        assert result is not None
        assert len(result) == MAX_RESOLVED_URL_LENGTH

    def test_resolved_length_over_cap_returns_none(self):
        result = resolve_url_template(
            "https://${env:HOST}",
            env={"HOST": "a" * (MAX_RESOLVED_URL_LENGTH + 1)},
            labels={},
        )
        assert result is None

    def test_label_with_control_char_returns_none(self):
        result = resolve_url_template(
            "${label:com.acme.url}",
            env={},
            labels={"com.acme.url": "https://app.example.com\n"},
        )
        assert result is None

    def test_value_with_unicode_nel_returns_none(self):
        # U+0085 NEXT LINE — treated as line terminator by some parsers.
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.comattacker.com"},
            labels={},
        )
        assert result is None

    def test_value_with_unicode_line_separator_returns_none(self):
        # U+2028 LINE SEPARATOR
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com attacker.com"},
            labels={},
        )
        assert result is None

    def test_value_with_unicode_paragraph_separator_returns_none(self):
        # U+2029 PARAGRAPH SEPARATOR
        result = resolve_url_template(
            "https://${env:VIRTUAL_HOST}",
            env={"VIRTUAL_HOST": "app.example.com attacker.com"},
            labels={},
        )
        assert result is None

    def test_value_with_space_passes(self):
        # Plain ASCII space is fine — not a line terminator. Resolution still
        # succeeds; the URL may be malformed downstream but that's not our
        # concern (we don't percent-encode here).
        result = resolve_url_template(
            "https://${env:HOST}",
            env={"HOST": "example.com/path with space"},
            labels={},
        )
        assert result == "https://example.com/path with space"
