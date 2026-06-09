"""Tests that ComposeClient._build_request carries env_files in the request payload."""
from deployment.compose_client import ComposeClient


def test_build_request_includes_env_files():
    client = ComposeClient()
    req = client._build_request(
        deployment_id="d1", project_name="p", compose_yaml="services: {}\n",
        action="up", env_file_content=None, env_files={".env": "A=1", ".db.env": "B=2"},
        profiles=None, remove_volumes=False, force_recreate=False, pull_images=False,
        wait_for_healthy=False, health_timeout=60, timeout=1800, stacks_dir=None,
        docker_host=None, tls_ca_cert=None, tls_cert=None, tls_key=None,
        registry_credentials=None,
    )
    assert req["env_files"] == {".env": "A=1", ".db.env": "B=2"}
