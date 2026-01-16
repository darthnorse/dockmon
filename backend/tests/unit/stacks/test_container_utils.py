"""
Unit tests for container_utils module.

Tests the utility functions that derive stack deployment info from container labels.
"""

import pytest

from deployment.container_utils import (
    HostInfo,
    StackDeploymentInfo,
    get_container_compose_project,
    get_container_compose_service,
    scan_deployed_stacks,
    get_deployed_hosts_for_stack,
)


class MockContainer:
    """Mock container object for testing."""

    def __init__(
        self,
        labels: dict = None,
        host_id: str = None,
        host_name: str = None,
        labels_none: bool = False,
    ):
        # Allow explicitly setting labels to None for testing edge cases
        if labels_none:
            self.labels = None
        else:
            self.labels = labels or {}
        self.host_id = host_id
        self.host_name = host_name


class TestHostInfo:
    """Test HostInfo dataclass."""

    def test_create_host_info(self):
        """Should create HostInfo with required fields."""
        host = HostInfo(host_id="host-123", host_name="MyHost")

        assert host.host_id == "host-123"
        assert host.host_name == "MyHost"


class TestStackDeploymentInfo:
    """Test StackDeploymentInfo dataclass."""

    def test_create_with_defaults(self):
        """Should create with empty lists and zero count by default."""
        info = StackDeploymentInfo(name="nginx")

        assert info.name == "nginx"
        assert info.hosts == []
        assert info.services == []
        assert info.container_count == 0

    def test_create_with_values(self):
        """Should create with provided values."""
        hosts = [HostInfo(host_id="h1", host_name="Host1")]
        info = StackDeploymentInfo(
            name="nginx",
            hosts=hosts,
            services=["web", "api"],
            container_count=5,
        )

        assert info.name == "nginx"
        assert len(info.hosts) == 1
        assert info.hosts[0].host_id == "h1"
        assert info.services == ["web", "api"]
        assert info.container_count == 5


class TestGetContainerComposeProject:
    """Test get_container_compose_project function."""

    def test_returns_project_name(self):
        """Should return project name from compose label."""
        container = MockContainer(
            labels={"com.docker.compose.project": "my-stack"}
        )

        result = get_container_compose_project(container)

        assert result == "my-stack"

    def test_returns_none_without_label(self):
        """Should return None if compose label not present."""
        container = MockContainer(labels={"other": "label"})

        result = get_container_compose_project(container)

        assert result is None

    def test_returns_none_for_empty_labels(self):
        """Should return None for empty labels dict."""
        container = MockContainer(labels={})

        result = get_container_compose_project(container)

        assert result is None

    def test_handles_none_labels(self):
        """Should handle container with None labels attribute."""
        container = MockContainer(labels_none=True)
        assert container.labels is None  # Verify labels is actually None

        result = get_container_compose_project(container)

        assert result is None

    def test_returns_none_for_empty_string_project(self):
        """Should return empty string (falsy) for empty project name."""
        container = MockContainer(
            labels={"com.docker.compose.project": ""}
        )

        result = get_container_compose_project(container)

        assert result == ""  # Returns empty string, not None

    def test_handles_missing_labels_attr(self):
        """Should handle container without labels attribute."""
        container = object()  # No labels attribute

        result = get_container_compose_project(container)

        assert result is None


class TestGetContainerComposeService:
    """Test get_container_compose_service function."""

    def test_returns_service_name(self):
        """Should return service name from compose label."""
        container = MockContainer(
            labels={"com.docker.compose.service": "web"}
        )

        result = get_container_compose_service(container)

        assert result == "web"

    def test_returns_none_without_label(self):
        """Should return None if service label not present."""
        container = MockContainer(
            labels={"com.docker.compose.project": "my-stack"}
        )

        result = get_container_compose_service(container)

        assert result is None

    def test_returns_none_for_empty_labels(self):
        """Should return None for empty labels dict."""
        container = MockContainer(labels={})

        result = get_container_compose_service(container)

        assert result is None

    def test_handles_none_labels(self):
        """Should handle container with None labels attribute."""
        container = MockContainer(labels_none=True)
        assert container.labels is None  # Verify labels is actually None

        result = get_container_compose_service(container)

        assert result is None

    def test_handles_missing_labels_attr(self):
        """Should handle container without labels attribute."""
        container = object()  # No labels attribute

        result = get_container_compose_service(container)

        assert result is None

    def test_returns_empty_string_for_empty_service(self):
        """Should return empty string (falsy) for empty service name."""
        container = MockContainer(
            labels={"com.docker.compose.service": ""}
        )

        result = get_container_compose_service(container)

        assert result == ""  # Returns empty string, not None


class TestScanDeployedStacks:
    """Test scan_deployed_stacks function."""

    def test_empty_container_list(self):
        """Should return empty dict for empty container list."""
        result = scan_deployed_stacks([])

        assert result == {}

    def test_containers_without_compose_labels(self):
        """Should skip containers without compose project label."""
        containers = [
            MockContainer(labels={"other": "label"}, host_id="host-1"),
            MockContainer(labels={}, host_id="host-2"),
        ]

        result = scan_deployed_stacks(containers)

        assert result == {}

    def test_single_stack_single_host(self):
        """Should track single stack on single host."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "nginx",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
        ]

        result = scan_deployed_stacks(containers)

        assert "nginx" in result
        info = result["nginx"]
        assert info.name == "nginx"
        assert info.container_count == 1
        assert len(info.hosts) == 1
        assert info.hosts[0].host_id == "host-1"
        assert info.hosts[0].host_name == "Host1"
        assert info.services == ["web"]

    def test_single_stack_multiple_services(self):
        """Should track multiple services for same stack."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "db",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "cache",
                },
                host_id="host-1",
                host_name="Host1",
            ),
        ]

        result = scan_deployed_stacks(containers)

        assert "myapp" in result
        info = result["myapp"]
        assert info.container_count == 3
        assert len(info.hosts) == 1  # Same host, not duplicated
        assert set(info.services) == {"web", "db", "cache"}

    def test_single_stack_multiple_hosts(self):
        """Should track same stack deployed to multiple hosts."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "nginx",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "nginx",
                    "com.docker.compose.service": "web",
                },
                host_id="host-2",
                host_name="Host2",
            ),
        ]

        result = scan_deployed_stacks(containers)

        assert "nginx" in result
        info = result["nginx"]
        assert info.container_count == 2
        assert len(info.hosts) == 2
        host_ids = {h.host_id for h in info.hosts}
        assert host_ids == {"host-1", "host-2"}

    def test_multiple_stacks(self):
        """Should track multiple different stacks."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "nginx",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "postgres",
                    "com.docker.compose.service": "db",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "redis",
                    "com.docker.compose.service": "cache",
                },
                host_id="host-2",
                host_name="Host2",
            ),
        ]

        result = scan_deployed_stacks(containers)

        assert len(result) == 3
        assert "nginx" in result
        assert "postgres" in result
        assert "redis" in result

        # nginx on host-1
        assert result["nginx"].hosts[0].host_id == "host-1"
        # postgres on host-1
        assert result["postgres"].hosts[0].host_id == "host-1"
        # redis on host-2
        assert result["redis"].hosts[0].host_id == "host-2"

    def test_deduplicates_hosts(self):
        """Should not duplicate hosts for multiple containers on same host."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
                host_name="Host1",
            ),
        ]

        result = scan_deployed_stacks(containers)

        info = result["myapp"]
        assert info.container_count == 3
        assert len(info.hosts) == 1  # Should deduplicate

    def test_deduplicates_services(self):
        """Should not duplicate services for scaled containers."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",
                },
                host_id="host-1",
            ),
            MockContainer(
                labels={
                    "com.docker.compose.project": "myapp",
                    "com.docker.compose.service": "web",  # Same service (scaled)
                },
                host_id="host-1",
            ),
        ]

        result = scan_deployed_stacks(containers)

        info = result["myapp"]
        assert info.container_count == 2
        assert info.services == ["web"]  # Should deduplicate

    def test_host_name_fallback_to_host_id(self):
        """Should use host_id as host_name if host_name is None."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-uuid-123",
                host_name=None,
            ),
        ]

        result = scan_deployed_stacks(containers)

        info = result["nginx"]
        assert info.hosts[0].host_id == "host-uuid-123"
        assert info.hosts[0].host_name == "host-uuid-123"  # Fallback

    def test_skips_container_without_host_id(self):
        """Should handle containers without host_id for host tracking."""
        containers = [
            MockContainer(
                labels={
                    "com.docker.compose.project": "nginx",
                    "com.docker.compose.service": "web",
                },
                host_id=None,
            ),
        ]

        result = scan_deployed_stacks(containers)

        # Stack is tracked but no hosts
        assert "nginx" in result
        info = result["nginx"]
        assert info.container_count == 1
        assert len(info.hosts) == 0
        assert info.services == ["web"]

    def test_mixed_compose_and_non_compose(self):
        """Should only track compose containers, skip others."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
            ),
            MockContainer(
                labels={"some.other.label": "value"},  # Not compose
                host_id="host-1",
            ),
            MockContainer(
                labels={},  # No labels
                host_id="host-2",
            ),
        ]

        result = scan_deployed_stacks(containers)

        assert len(result) == 1
        assert "nginx" in result


class TestGetDeployedHostsForStack:
    """Test get_deployed_hosts_for_stack function."""

    def test_empty_container_list(self):
        """Should return empty list for empty containers."""
        result = get_deployed_hosts_for_stack([], "nginx")

        assert result == []

    def test_stack_not_found(self):
        """Should return empty list if stack not deployed."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "postgres"},
                host_id="host-1",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert result == []

    def test_single_host(self):
        """Should return single host for stack."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert len(result) == 1
        assert result[0].host_id == "host-1"
        assert result[0].host_name == "Host1"

    def test_multiple_hosts(self):
        """Should return all hosts where stack is deployed."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-2",
                host_name="Host2",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-3",
                host_name="Host3",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert len(result) == 3
        host_ids = {h.host_id for h in result}
        assert host_ids == {"host-1", "host-2", "host-3"}

    def test_deduplicates_hosts(self):
        """Should not duplicate hosts for multiple containers on same host."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",  # Same host
                host_name="Host1",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",  # Same host
                host_name="Host1",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert len(result) == 1

    def test_filters_by_stack_name(self):
        """Should only return hosts for specified stack."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "postgres"},
                host_id="host-2",
                host_name="Host2",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert len(result) == 1
        assert result[0].host_id == "host-1"

    def test_skips_containers_without_host_id(self):
        """Should skip containers without host_id."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id=None,
            ),
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert len(result) == 1
        assert result[0].host_id == "host-1"

    def test_host_name_fallback(self):
        """Should use host_id as host_name fallback."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-uuid-123",
                host_name=None,
            ),
        ]

        result = get_deployed_hosts_for_stack(containers, "nginx")

        assert result[0].host_name == "host-uuid-123"

    def test_case_sensitive_matching(self):
        """Should match stack name case-sensitively."""
        containers = [
            MockContainer(
                labels={"com.docker.compose.project": "nginx"},
                host_id="host-1",
                host_name="Host1",
            ),
            MockContainer(
                labels={"com.docker.compose.project": "Nginx"},
                host_id="host-2",
                host_name="Host2",
            ),
        ]

        # Should only match exact case
        result = get_deployed_hosts_for_stack(containers, "nginx")
        assert len(result) == 1
        assert result[0].host_id == "host-1"

        result_upper = get_deployed_hosts_for_stack(containers, "Nginx")
        assert len(result_upper) == 1
        assert result_upper[0].host_id == "host-2"

        # Different case should not match
        result_wrong = get_deployed_hosts_for_stack(containers, "NGINX")
        assert len(result_wrong) == 0
