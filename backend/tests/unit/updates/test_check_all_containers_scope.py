"""check_all_containers(host_ids=...) checks only containers on those hosts."""

from unittest.mock import AsyncMock, MagicMock, patch

from database import DatabaseManager
from updates.update_checker import UpdateChecker


async def test_host_ids_limits_the_check_to_those_hosts():
    checker = UpdateChecker(db=MagicMock(spec=DatabaseManager), monitor=MagicMock())
    containers = [
        {"host_id": "h1", "id": "aaa111111111", "name": "a", "image": "nginx:latest"},
        {"host_id": "h2", "id": "ccc333333333", "name": "c", "image": "nginx:latest"},
    ]
    session = MagicMock()
    session.query.return_value.first.return_value = MagicMock(skip_compose_containers=False)
    checker.db.get_session.return_value.__enter__.return_value = session
    checked = []

    async def check_one(container):
        checked.append(container["host_id"])
        return None

    with patch.object(checker, "_get_all_containers", AsyncMock(return_value=containers)), \
         patch.object(checker, "_get_ignore_patterns", return_value=[]), \
         patch.object(checker, "_is_compose_container", return_value=False), \
         patch.object(checker, "_check_container_update", side_effect=check_one):
        stats = await checker.check_all_containers(host_ids={"h1"})

    assert stats["total"] == 1
    assert checked == ["h1"]
