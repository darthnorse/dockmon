"""deployment_service_progress must carry the deployment's real host id.

Imported deployments have bare UUID ids (deployment/routes.py import path), so
the host cannot be parsed from the id prefix the way transient ids allow.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from database import Deployment, DockerHostDB
from deployment.agent_executor import AgentDeploymentExecutor

HOST_ID = "ebe8b950-6e8f-4901-8585-8b63b65949db"


async def test_service_progress_uses_deployment_record_host(test_db):
    test_db.add(DockerHostDB(id=HOST_ID, name="imported-host", url="agent://", is_active=True,
                             created_at=datetime.now(timezone.utc)))
    deployment_id = str(uuid.uuid4())
    test_db.add(Deployment(id=deployment_id, host_id=HOST_ID, stack_name="stack", status="running"))
    test_db.commit()

    @contextmanager
    def get_session():
        yield test_db

    monitor = SimpleNamespace(manager=MagicMock(broadcast=AsyncMock()))
    executor = AgentDeploymentExecutor(monitor=monitor, database_manager=SimpleNamespace(get_session=get_session))

    await executor._emit_service_progress(deployment_id, [{"name": "web", "status": "running"}])

    payload = monitor.manager.broadcast.await_args.args[0]
    assert payload["type"] == "deployment_service_progress"
    assert payload["host_id"] == HOST_ID
