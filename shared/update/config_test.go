package update

import (
	"testing"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
	"github.com/sirupsen/logrus"
)

// =============================================================================
// Test extractUserLabels() - Label Filtering (from test_label_merge.py)
// =============================================================================

func TestExtractUserLabels_RemovesImageLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"org.opencontainers.image.version": "1.0.0",
	}
	oldImageLabels := map[string]string{
		"org.opencontainers.image.version": "1.0.0",
	}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// Image label removed - Docker will merge from new image
	if len(result) != 0 {
		t.Errorf("Expected empty labels, got %v", result)
	}
}

func TestExtractUserLabels_PreservesComposeLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"com.docker.compose.project":       "mystack",
		"org.opencontainers.image.version": "1.0.0",
	}
	oldImageLabels := map[string]string{
		"org.opencontainers.image.version": "1.0.0",
	}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// Compose label preserved, image label removed
	if len(result) != 1 {
		t.Errorf("Expected 1 label, got %d", len(result))
	}
	if result["com.docker.compose.project"] != "mystack" {
		t.Errorf("Expected compose project label, got %v", result)
	}
}

func TestExtractUserLabels_PreservesDockmonLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"dockmon.deployment_id":            "uuid-123",
		"dockmon.managed":                  "true",
		"org.opencontainers.image.version": "1.0.0",
	}
	oldImageLabels := map[string]string{
		"org.opencontainers.image.version": "1.0.0",
	}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// DockMon labels preserved, image label removed
	if len(result) != 2 {
		t.Errorf("Expected 2 labels, got %d", len(result))
	}
	if result["dockmon.deployment_id"] != "uuid-123" {
		t.Errorf("Expected dockmon.deployment_id=uuid-123, got %v", result["dockmon.deployment_id"])
	}
	if result["dockmon.managed"] != "true" {
		t.Errorf("Expected dockmon.managed=true, got %v", result["dockmon.managed"])
	}
}

func TestExtractUserLabels_PreservesCustomLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"custom.environment": "production",
		"traefik.enable":     "true",
	}
	oldImageLabels := map[string]string{}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// All custom labels preserved (no image labels to remove)
	if len(result) != 2 {
		t.Errorf("Expected 2 labels, got %d", len(result))
	}
	if result["custom.environment"] != "production" {
		t.Errorf("Expected custom.environment=production")
	}
	if result["traefik.enable"] != "true" {
		t.Errorf("Expected traefik.enable=true")
	}
}

func TestExtractUserLabels_EmptyContainerLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{}
	oldImageLabels := map[string]string{
		"org.opencontainers.image.version": "2.0.0",
	}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// No container labels = no user labels
	if len(result) != 0 {
		t.Errorf("Expected empty labels, got %v", result)
	}
}

func TestExtractUserLabels_EmptyImageLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"custom.environment": "production",
	}
	oldImageLabels := map[string]string{}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// No image labels to subtract = all container labels preserved
	if len(result) != 1 {
		t.Errorf("Expected 1 label, got %d", len(result))
	}
	if result["custom.environment"] != "production" {
		t.Errorf("Expected custom.environment=production")
	}
}

func TestExtractUserLabels_BothEmpty(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	result := extractUserLabels(log, map[string]string{}, map[string]string{})

	if len(result) != 0 {
		t.Errorf("Expected empty labels, got %v", result)
	}
}

func TestExtractUserLabels_NilContainerLabels(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	result := extractUserLabels(log, nil, map[string]string{"key": "value"})

	// Defensive handling of nil
	if result == nil {
		t.Error("Expected non-nil map")
	}
	if len(result) != 0 {
		t.Errorf("Expected empty labels, got %v", result)
	}
}

func TestExtractUserLabels_ResolvesConflictsInFavorOfImage(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	containerLabels := map[string]string{
		"app.version":                      "1.0",
		"org.opencontainers.image.version": "1.0.0",
	}
	oldImageLabels := map[string]string{
		"app.version":                      "1.0",
		"org.opencontainers.image.version": "1.0.0",
	}

	result := extractUserLabels(log, containerLabels, oldImageLabels)

	// Both labels matched old image = both removed
	if len(result) != 0 {
		t.Errorf("Expected empty labels, got %v", result)
	}
}

// =============================================================================
// Test applyPodmanFixes() - Podman Compatibility (from test_passthrough_critical.py)
// =============================================================================

func TestApplyPodmanFixes_ConvertNanoCpusToCpuQuota(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	hostConfig := &container.HostConfig{
		Resources: container.Resources{
			NanoCPUs:  2000000000, // 2 CPUs
			CPUPeriod: 0,
			CPUQuota:  0,
		},
	}

	applyPodmanFixes(log, hostConfig)

	// NanoCpus should be removed and converted to CpuPeriod/CpuQuota
	if hostConfig.NanoCPUs != 0 {
		t.Errorf("Expected NanoCPUs=0, got %d", hostConfig.NanoCPUs)
	}
	if hostConfig.CPUPeriod != 100000 {
		t.Errorf("Expected CPUPeriod=100000, got %d", hostConfig.CPUPeriod)
	}
	if hostConfig.CPUQuota != 200000 {
		t.Errorf("Expected CPUQuota=200000 (2 CPUs), got %d", hostConfig.CPUQuota)
	}
}

func TestApplyPodmanFixes_RemoveMemorySwappiness(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	swappiness := int64(60)
	hostConfig := &container.HostConfig{
		Resources: container.Resources{
			Memory:           536870912,
			MemorySwappiness: &swappiness,
		},
	}

	applyPodmanFixes(log, hostConfig)

	// MemorySwappiness should be removed
	if hostConfig.MemorySwappiness != nil {
		t.Errorf("Expected MemorySwappiness=nil, got %v", *hostConfig.MemorySwappiness)
	}
	// Memory preserved
	if hostConfig.Memory != 536870912 {
		t.Errorf("Expected Memory=536870912, got %d", hostConfig.Memory)
	}
}

func TestApplyPodmanFixes_PreservesExistingCpuPeriodQuota(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	hostConfig := &container.HostConfig{
		Resources: container.Resources{
			NanoCPUs:  1000000000, // 1 CPU
			CPUPeriod: 50000,      // Already set
			CPUQuota:  25000,      // Already set
		},
	}

	applyPodmanFixes(log, hostConfig)

	// Should NOT overwrite existing CpuPeriod/CpuQuota
	if hostConfig.CPUPeriod != 50000 {
		t.Errorf("Expected CPUPeriod=50000 (unchanged), got %d", hostConfig.CPUPeriod)
	}
	if hostConfig.CPUQuota != 25000 {
		t.Errorf("Expected CPUQuota=25000 (unchanged), got %d", hostConfig.CPUQuota)
	}
}

func TestApplyPodmanFixes_SingleCpu(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	hostConfig := &container.HostConfig{
		Resources: container.Resources{
			NanoCPUs: 1000000000, // 1 CPU
		},
	}

	applyPodmanFixes(log, hostConfig)

	if hostConfig.CPUPeriod != 100000 {
		t.Errorf("Expected CPUPeriod=100000, got %d", hostConfig.CPUPeriod)
	}
	if hostConfig.CPUQuota != 100000 {
		t.Errorf("Expected CPUQuota=100000 (1 CPU), got %d", hostConfig.CPUQuota)
	}
}

func TestApplyPodmanFixes_HalfCpu(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	hostConfig := &container.HostConfig{
		Resources: container.Resources{
			NanoCPUs: 500000000, // 0.5 CPU
		},
	}

	applyPodmanFixes(log, hostConfig)

	if hostConfig.CPUPeriod != 100000 {
		t.Errorf("Expected CPUPeriod=100000, got %d", hostConfig.CPUPeriod)
	}
	if hostConfig.CPUQuota != 50000 {
		t.Errorf("Expected CPUQuota=50000 (0.5 CPU), got %d", hostConfig.CPUQuota)
	}
}

// =============================================================================
// Test extractNetworkConfig() - Network Extraction (from test_passthrough_v2_comprehensive.py)
// =============================================================================

func TestExtractNetworkConfig_BridgeMode(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "bridge",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	if primaryNet != nil {
		t.Error("Expected nil primary network config for bridge mode")
	}
	if additionalNets != nil {
		t.Error("Expected nil additional networks for bridge mode")
	}
}

func TestExtractNetworkConfig_HostMode(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "host",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	if primaryNet != nil {
		t.Error("Expected nil primary network config for host mode")
	}
	if additionalNets != nil {
		t.Error("Expected nil additional networks for host mode")
	}
}

func TestExtractNetworkConfig_ContainerMode(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "container:gluetun",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	if primaryNet != nil {
		t.Error("Expected nil primary network config for container mode")
	}
	if additionalNets != nil {
		t.Error("Expected nil additional networks for container mode")
	}
}

func TestExtractNetworkConfig_SingleCustomNetworkNoConfig(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "my-custom-net",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{
				"my-custom-net": {
					NetworkID: "abc123",
					Gateway:   "172.18.0.1",
					IPAddress: "172.18.0.5", // Dynamic (assigned by Docker)
					Aliases:   nil,
				},
			},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	// Simple network connection - no manual config needed (no static IP or aliases)
	if primaryNet != nil {
		t.Error("Expected nil primary network config for simple network")
	}
	if additionalNets != nil {
		t.Error("Expected nil additional networks for single network")
	}
}

func TestExtractNetworkConfig_SingleCustomNetworkWithStaticIP(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "my-custom-net",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{
				"my-custom-net": {
					NetworkID: "abc123",
					IPAddress: "172.18.0.100",
					IPAMConfig: &network.EndpointIPAMConfig{
						IPv4Address: "172.18.0.100", // User-configured
					},
					Gateway: "172.18.0.1",
					Aliases: nil,
				},
			},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	// Manual connection required for static IP
	if primaryNet == nil {
		t.Fatal("Expected primary network config for static IP")
	}
	if primaryNet.EndpointsConfig == nil {
		t.Fatal("Expected EndpointsConfig in primary network")
	}
	if _, exists := primaryNet.EndpointsConfig["my-custom-net"]; !exists {
		t.Error("Expected my-custom-net in EndpointsConfig")
	}
	// Verify static IP is preserved
	endpoint := primaryNet.EndpointsConfig["my-custom-net"]
	if endpoint.IPAMConfig == nil || endpoint.IPAMConfig.IPv4Address != "172.18.0.100" {
		t.Error("Expected static IP 172.18.0.100 to be preserved")
	}
	if additionalNets != nil {
		t.Error("Expected nil additional networks for single network")
	}
}

func TestExtractNetworkConfig_SingleCustomNetworkWithAliases(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "my-custom-net",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{
				"my-custom-net": {
					NetworkID: "abc123",
					IPAddress: "172.18.0.5",
					Aliases:   []string{"web", "frontend", "abc123def456"}, // Last one is auto-generated
				},
			},
		},
	}

	primaryNet, _ := extractNetworkConfig(log, inspect)

	// Manual connection required for aliases
	if primaryNet == nil {
		t.Fatal("Expected primary network config for aliases")
	}
	endpoint := primaryNet.EndpointsConfig["my-custom-net"]
	if endpoint == nil {
		t.Fatal("Expected endpoint config")
	}
	// Should filter out 12-char auto-generated alias
	if len(endpoint.Aliases) != 2 {
		t.Errorf("Expected 2 aliases (filtering out 12-char auto-generated), got %d: %v", len(endpoint.Aliases), endpoint.Aliases)
	}
}

func TestExtractNetworkConfig_MultipleNetworks(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "frontend-net",
			},
		},
		NetworkSettings: &types.NetworkSettings{
			Networks: map[string]*network.EndpointSettings{
				"frontend-net": {
					NetworkID: "abc123",
					IPAddress: "172.18.0.10",
					IPAMConfig: &network.EndpointIPAMConfig{
						IPv4Address: "172.18.0.10",
					},
					Aliases: []string{"web"},
				},
				"backend-net": {
					NetworkID: "def456",
					IPAddress: "172.19.0.10",
					IPAMConfig: &network.EndpointIPAMConfig{
						IPv4Address: "172.19.0.10",
					},
					Aliases: []string{"api"},
				},
			},
		},
	}

	primaryNet, additionalNets := extractNetworkConfig(log, inspect)

	// Primary network should have config
	if primaryNet == nil {
		t.Fatal("Expected primary network config")
	}
	if primaryNet.EndpointsConfig["frontend-net"] == nil {
		t.Error("Expected frontend-net as primary")
	}

	// Additional network should be returned
	if additionalNets == nil {
		t.Fatal("Expected additional networks")
	}
	if additionalNets["backend-net"] == nil {
		t.Error("Expected backend-net in additional networks")
	}
}

func TestExtractNetworkConfig_EmptyNetworkSettings(t *testing.T) {
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	inspect := &types.ContainerJSON{
		ContainerJSONBase: &types.ContainerJSONBase{
			HostConfig: &container.HostConfig{
				NetworkMode: "bridge",
			},
		},
		NetworkSettings: nil,
	}

	primaryNet, _ := extractNetworkConfig(log, inspect)

	if primaryNet != nil {
		t.Error("Expected nil primary network config for nil NetworkSettings")
	}
}

// =============================================================================
// Test buildEndpointConfig() - Endpoint Settings
// =============================================================================

func TestBuildEndpointConfig_WithStaticIP(t *testing.T) {
	data := &network.EndpointSettings{
		IPAMConfig: &network.EndpointIPAMConfig{
			IPv4Address: "172.18.0.100",
		},
	}

	result := buildEndpointConfig(data)

	if result.IPAMConfig == nil {
		t.Fatal("Expected IPAMConfig")
	}
	if result.IPAMConfig.IPv4Address != "172.18.0.100" {
		t.Errorf("Expected IPv4Address=172.18.0.100, got %s", result.IPAMConfig.IPv4Address)
	}
}

func TestBuildEndpointConfig_WithIPv6(t *testing.T) {
	data := &network.EndpointSettings{
		IPAMConfig: &network.EndpointIPAMConfig{
			IPv4Address: "172.18.0.100",
			IPv6Address: "2001:db8::1",
		},
	}

	result := buildEndpointConfig(data)

	if result.IPAMConfig == nil {
		t.Fatal("Expected IPAMConfig")
	}
	if result.IPAMConfig.IPv4Address != "172.18.0.100" {
		t.Error("Expected IPv4 to be preserved")
	}
	if result.IPAMConfig.IPv6Address != "2001:db8::1" {
		t.Error("Expected IPv6 to be preserved")
	}
}

func TestBuildEndpointConfig_FiltersAutoGeneratedAliases(t *testing.T) {
	data := &network.EndpointSettings{
		Aliases: []string{"web", "frontend", "abc123def456"}, // Last is 12-char auto-generated
	}

	result := buildEndpointConfig(data)

	if len(result.Aliases) != 2 {
		t.Errorf("Expected 2 aliases (filtered 12-char), got %d", len(result.Aliases))
	}
}

func TestBuildEndpointConfig_PreservesLinks(t *testing.T) {
	data := &network.EndpointSettings{
		Links: []string{"db:database", "cache:redis"},
	}

	result := buildEndpointConfig(data)

	if len(result.Links) != 2 {
		t.Errorf("Expected 2 links, got %d", len(result.Links))
	}
}

func TestBuildEndpointConfig_EmptyConfig(t *testing.T) {
	data := &network.EndpointSettings{}

	result := buildEndpointConfig(data)

	if result.IPAMConfig != nil {
		t.Error("Expected nil IPAMConfig for empty data")
	}
	if result.Aliases != nil {
		t.Error("Expected nil Aliases for empty data")
	}
	if result.Links != nil {
		t.Error("Expected nil Links for empty data")
	}
}
