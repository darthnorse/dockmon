"""
Tests that regex:-prefixed selector values are ReDoS-validated.

The engine matches host_selector['host_name'] / container_selector['container_name']
as a regex when they start with 'regex:', but the validator only checked a separate
top-level 'regex' key, so a catastrophic pattern could be stored and then run on the
evaluation loop every cycle.
"""

import pytest

from alerts.validator import AlertRuleValidator, AlertRuleValidationError


@pytest.fixture
def validator():
    return AlertRuleValidator()


class TestSelectorRegexValidation:
    def test_rejects_dangerous_regex_in_host_name(self, validator):
        with pytest.raises(AlertRuleValidationError):
            validator._validate_selectors({'host_selector_json': {'host_name': 'regex:(.+)+'}})

    def test_rejects_invalid_regex_in_container_name(self, validator):
        with pytest.raises(AlertRuleValidationError):
            validator._validate_selectors({'container_selector_json': {'container_name': 'regex:(unclosed'}})

    def test_allows_plain_exact_selector(self, validator):
        # No exception for a non-regex exact match.
        validator._validate_selectors({'host_selector_json': {'host_name': 'web-01'}})

    def test_allows_safe_regex_selector(self, validator):
        validator._validate_selectors({'container_selector_json': {'container_name': 'regex:^web-[0-9]+$'}})
