from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from checker_fakes import CHANGELOG_CHECKED_AT, CHANGELOG_URL


@pytest.fixture
def changelog_stub():
    resolved = (CHANGELOG_URL, "auto", CHANGELOG_CHECKED_AT)
    with patch("updates.update_checker.resolve_changelog_url", AsyncMock(return_value=resolved)) as stub:
        yield stub


@pytest.fixture
def credentials_stub():
    with patch("utils.registry_credentials.get_registry_credentials", return_value=None) as stub:
        yield stub


@pytest.fixture
def event_bus_stub():
    bus = SimpleNamespace(emit=AsyncMock())
    with patch("updates.update_checker.get_event_bus", return_value=bus):
        yield bus
