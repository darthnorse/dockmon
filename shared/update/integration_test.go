// +build integration

package update

import (
	"context"
	"fmt"
	"io"
	"os"
	"testing"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
	"github.com/sirupsen/logrus"
)

// Integration tests require Docker to be running.
// Run with: go test -tags=integration -v ./...

// =============================================================================
// Test Helpers
// =============================================================================

func getDockerClient(t *testing.T) *client.Client {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		t.Skipf("Docker not available: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := cli.Ping(ctx); err != nil {
		t.Skipf("Docker not available: %v", err)
	}
	return cli
}

func pullImage(t *testing.T, cli *client.Client, imageName string) {
	ctx := context.Background()
	// Try to get image first
	if _, _, err := cli.ImageInspectWithRaw(ctx, imageName); err == nil {
		return // Image already exists
	}
	// Pull image
	reader, err := cli.ImagePull(ctx, imageName, image.PullOptions{})
	if err != nil {
		t.Fatalf("Failed to pull image %s: %v", imageName, err)
	}
	// Drain the reader to complete the pull
	io.Copy(io.Discard, reader)
	reader.Close()
	// Wait for image to be available
	time.Sleep(1 * time.Second)
}

func removeContainer(cli *client.Client, containerID string) {
	ctx := context.Background()
	timeout := 5
	cli.ContainerStop(ctx, containerID, container.StopOptions{Timeout: &timeout})
	cli.ContainerRemove(ctx, containerID, container.RemoveOptions{Force: true})
}

func removeNetwork(cli *client.Client, networkID string) {
	ctx := context.Background()
	cli.NetworkRemove(ctx, networkID)
}

// =============================================================================
// Integration Test: Volume Passthrough (Issue #68)
// =============================================================================

func TestIntegration_VolumePassthrough(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull alpine image
	pullImage(t, cli, "alpine:latest")

	// Create temp directory for bind mount
	tmpDir, err := os.MkdirTemp("", "dockmon-test-")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	containerName := fmt.Sprintf("dockmon-test-volumes-%d", time.Now().Unix())

	// Create container with multiple volumes
	resp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		&container.HostConfig{
			Binds: []string{
				fmt.Sprintf("%s:/config:rw", tmpDir),
			},
			Tmpfs: map[string]string{
				"/tmp": "size=100m,mode=1777",
			},
		},
		nil, nil, containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer removeContainer(cli, resp.ID)

	// Start container
	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Inspect container
	inspect, err := cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect container: %v", err)
	}

	// Extract config
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "alpine:latest", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Verify Binds preserved
	if len(extracted.HostConfig.Binds) != 1 {
		t.Errorf("Expected 1 bind mount, got %d", len(extracted.HostConfig.Binds))
	}

	// Verify Tmpfs preserved
	if len(extracted.HostConfig.Tmpfs) != 1 {
		t.Errorf("Expected 1 tmpfs mount, got %d", len(extracted.HostConfig.Tmpfs))
	}
	if _, exists := extracted.HostConfig.Tmpfs["/tmp"]; !exists {
		t.Error("Tmpfs /tmp should be preserved")
	}

	t.Log("Volume passthrough: OK")
}

// =============================================================================
// Integration Test: Static IP Preservation
// =============================================================================

func TestIntegration_StaticIPPreservation(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull alpine image
	pullImage(t, cli, "alpine:latest")

	// Create custom network with subnet
	networkName := fmt.Sprintf("dockmon-test-net-%d", time.Now().Unix())
	subnet := "10.99.0.0/16"
	gateway := "10.99.0.1"
	staticIP := "10.99.0.10"

	netResp, err := cli.NetworkCreate(ctx, networkName, network.CreateOptions{
		Driver: "bridge",
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{
				{
					Subnet:  subnet,
					Gateway: gateway,
				},
			},
		},
	})
	if err != nil {
		t.Fatalf("Failed to create network: %v", err)
	}
	defer removeNetwork(cli, netResp.ID)

	// Create container with static IP
	containerName := fmt.Sprintf("dockmon-test-staticip-%d", time.Now().Unix())

	resp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		&container.HostConfig{
			NetworkMode: container.NetworkMode(networkName),
		},
		&network.NetworkingConfig{
			EndpointsConfig: map[string]*network.EndpointSettings{
				networkName: {
					IPAMConfig: &network.EndpointIPAMConfig{
						IPv4Address: staticIP,
					},
				},
			},
		},
		nil, containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer removeContainer(cli, resp.ID)

	// Start container
	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Inspect container
	inspect, err := cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect container: %v", err)
	}

	// Extract config
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "alpine:latest", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Verify network config extracted
	if extracted.NetworkingConfig == nil {
		t.Fatal("NetworkingConfig should be present for static IP")
	}

	if extracted.NetworkingConfig.EndpointsConfig[networkName] == nil {
		t.Fatalf("Network %s should be in EndpointsConfig", networkName)
	}

	endpoint := extracted.NetworkingConfig.EndpointsConfig[networkName]
	if endpoint.IPAMConfig == nil || endpoint.IPAMConfig.IPv4Address != staticIP {
		t.Errorf("Static IP should be %s, got %v", staticIP, endpoint.IPAMConfig)
	}

	t.Log("Static IP preservation: OK")
}

// =============================================================================
// Integration Test: NetworkMode container:X Resolution
// =============================================================================

func TestIntegration_NetworkModeContainerResolution(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull alpine image
	pullImage(t, cli, "alpine:latest")

	// Create provider container (like gluetun VPN)
	providerName := fmt.Sprintf("dockmon-test-provider-%d", time.Now().Unix())
	providerResp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		nil, nil, nil, providerName,
	)
	if err != nil {
		t.Fatalf("Failed to create provider container: %v", err)
	}
	defer removeContainer(cli, providerResp.ID)

	if err := cli.ContainerStart(ctx, providerResp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start provider container: %v", err)
	}

	// Create dependent container using container:ID network mode
	dependentName := fmt.Sprintf("dockmon-test-dependent-%d", time.Now().Unix())
	dependentResp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		&container.HostConfig{
			NetworkMode: container.NetworkMode(fmt.Sprintf("container:%s", providerResp.ID)),
		},
		nil, nil, dependentName,
	)
	if err != nil {
		t.Fatalf("Failed to create dependent container: %v", err)
	}
	defer removeContainer(cli, dependentResp.ID)

	if err := cli.ContainerStart(ctx, dependentResp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start dependent container: %v", err)
	}

	// Inspect dependent container
	inspect, err := cli.ContainerInspect(ctx, dependentResp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect dependent container: %v", err)
	}

	// Extract config - should resolve ID to name
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "alpine:latest", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Verify NetworkMode was resolved to container:name
	expectedNetworkMode := fmt.Sprintf("container:%s", providerName)
	if string(extracted.HostConfig.NetworkMode) != expectedNetworkMode {
		t.Errorf("NetworkMode should be %s, got %s", expectedNetworkMode, extracted.HostConfig.NetworkMode)
	}

	t.Log("NetworkMode container resolution: OK")
}

// =============================================================================
// Integration Test: Full Update Workflow
// =============================================================================

func TestIntegration_FullUpdateWorkflow(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull both alpine versions
	pullImage(t, cli, "alpine:3.18")
	pullImage(t, cli, "alpine:3.19")

	// Create temp directory
	tmpDir, err := os.MkdirTemp("", "dockmon-test-update-")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	containerName := fmt.Sprintf("dockmon-test-update-%d", time.Now().Unix())

	// Create original container with alpine:3.18
	resp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:3.18",
			Cmd:   []string{"sleep", "300"},
			Env:   []string{"TEST_VAR=original"},
			Labels: map[string]string{
				"custom.label": "preserved",
			},
		},
		&container.HostConfig{
			Binds: []string{
				fmt.Sprintf("%s:/data:rw", tmpDir),
			},
			RestartPolicy: container.RestartPolicy{
				Name: "unless-stopped",
			},
		},
		nil, nil, containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer removeContainer(cli, resp.ID)

	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Inspect old container
	inspect, err := cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect container: %v", err)
	}

	// Extract config for recreation with new image
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "alpine:3.19", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Stop and remove old container
	timeout := 5
	cli.ContainerStop(ctx, resp.ID, container.StopOptions{Timeout: &timeout})
	cli.ContainerRemove(ctx, resp.ID, container.RemoveOptions{Force: true})

	// Create new container with extracted config
	newResp, err := cli.ContainerCreate(ctx,
		extracted.Config,
		extracted.HostConfig,
		extracted.NetworkingConfig,
		nil,
		containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create new container: %v", err)
	}
	defer removeContainer(cli, newResp.ID)

	if err := cli.ContainerStart(ctx, newResp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start new container: %v", err)
	}

	// Inspect new container and verify configuration preserved
	newInspect, err := cli.ContainerInspect(ctx, newResp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect new container: %v", err)
	}

	// Verify image updated
	if newInspect.Config.Image != "alpine:3.19" {
		t.Errorf("Image should be alpine:3.19, got %s", newInspect.Config.Image)
	}

	// Verify environment preserved
	envFound := false
	for _, e := range newInspect.Config.Env {
		if e == "TEST_VAR=original" {
			envFound = true
			break
		}
	}
	if !envFound {
		t.Error("Environment variable TEST_VAR=original should be preserved")
	}

	// Verify volume preserved
	if len(newInspect.HostConfig.Binds) != 1 {
		t.Errorf("Should have 1 bind mount, got %d", len(newInspect.HostConfig.Binds))
	}

	// Verify restart policy preserved
	if newInspect.HostConfig.RestartPolicy.Name != "unless-stopped" {
		t.Errorf("Restart policy should be unless-stopped, got %s", newInspect.HostConfig.RestartPolicy.Name)
	}

	// Verify custom label preserved
	if newInspect.Config.Labels["custom.label"] != "preserved" {
		t.Errorf("Custom label should be preserved")
	}

	t.Log("Full update workflow: OK")
}

// =============================================================================
// Integration Test: Port Bindings Preservation
// =============================================================================

func TestIntegration_PortBindingsPreservation(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull nginx image
	pullImage(t, cli, "nginx:alpine")

	containerName := fmt.Sprintf("dockmon-test-ports-%d", time.Now().Unix())

	// Create container with port bindings
	resp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "nginx:alpine",
			ExposedPorts: nat.PortSet{
				"80/tcp": struct{}{},
			},
		},
		&container.HostConfig{
			PortBindings: nat.PortMap{
				"80/tcp": []nat.PortBinding{
					{HostIP: "0.0.0.0", HostPort: "8888"},
				},
			},
		},
		nil, nil, containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer removeContainer(cli, resp.ID)

	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Inspect container
	inspect, err := cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect container: %v", err)
	}

	// Extract config
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "nginx:alpine", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Verify port bindings preserved
	portBindings := extracted.HostConfig.PortBindings
	if len(portBindings) == 0 {
		t.Fatal("Port bindings should be preserved")
	}

	bindings, exists := portBindings["80/tcp"]
	if !exists || len(bindings) == 0 {
		t.Fatal("Port 80/tcp bindings should exist")
	}

	if bindings[0].HostPort != "8888" {
		t.Errorf("HostPort should be 8888, got %s", bindings[0].HostPort)
	}

	t.Log("Port bindings preservation: OK")
}

// =============================================================================
// Integration Test: Multiple Networks
// =============================================================================

func TestIntegration_MultipleNetworks(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull alpine image
	pullImage(t, cli, "alpine:latest")

	timestamp := time.Now().Unix()
	net1Name := fmt.Sprintf("dockmon-test-net1-%d", timestamp)
	net2Name := fmt.Sprintf("dockmon-test-net2-%d", timestamp)
	containerName := fmt.Sprintf("dockmon-test-multinet-%d", timestamp)

	// Create two networks
	net1Resp, err := cli.NetworkCreate(ctx, net1Name, network.CreateOptions{Driver: "bridge"})
	if err != nil {
		t.Fatalf("Failed to create network 1: %v", err)
	}
	defer removeNetwork(cli, net1Resp.ID)

	net2Resp, err := cli.NetworkCreate(ctx, net2Name, network.CreateOptions{Driver: "bridge"})
	if err != nil {
		t.Fatalf("Failed to create network 2: %v", err)
	}
	defer removeNetwork(cli, net2Resp.ID)

	// Create container on first network
	resp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		&container.HostConfig{
			NetworkMode: container.NetworkMode(net1Name),
		},
		nil, nil, containerName,
	)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer removeContainer(cli, resp.ID)

	// Connect to second network with alias
	if err := cli.NetworkConnect(ctx, net2Name, resp.ID, &network.EndpointSettings{
		Aliases: []string{"my-service"},
	}); err != nil {
		t.Fatalf("Failed to connect to network 2: %v", err)
	}

	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Inspect container
	inspect, err := cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect container: %v", err)
	}

	// Verify container is on both networks
	if len(inspect.NetworkSettings.Networks) < 2 {
		t.Fatalf("Container should be on 2 networks, got %d", len(inspect.NetworkSettings.Networks))
	}

	// Extract config
	extracted, err := ExtractConfig(ctx, cli, log, &inspect, "alpine:latest", nil, nil, false)
	if err != nil {
		t.Fatalf("Failed to extract config: %v", err)
	}

	// Verify additional networks extracted
	if extracted.AdditionalNets == nil || len(extracted.AdditionalNets) == 0 {
		t.Fatal("Additional networks should be extracted")
	}

	// Verify alias preserved
	net2Config, exists := extracted.AdditionalNets[net2Name]
	if !exists {
		t.Fatalf("Network %s should be in additional networks", net2Name)
	}

	aliasFound := false
	for _, alias := range net2Config.Aliases {
		if alias == "my-service" {
			aliasFound = true
			break
		}
	}
	if !aliasFound {
		t.Errorf("Alias 'my-service' should be preserved, got %v", net2Config.Aliases)
	}

	t.Log("Multiple networks: OK")
}

// =============================================================================
// Integration Test: Dependent Container Detection
// =============================================================================

func TestIntegration_DependentContainerDetection(t *testing.T) {
	cli := getDockerClient(t)
	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	// Pull alpine image
	pullImage(t, cli, "alpine:latest")

	timestamp := time.Now().Unix()
	parentName := fmt.Sprintf("dockmon-test-parent-%d", timestamp)
	dependentName := fmt.Sprintf("dockmon-test-dependent-%d", timestamp)

	// Create parent container (like gluetun VPN)
	parentResp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		nil, nil, nil, parentName,
	)
	if err != nil {
		t.Fatalf("Failed to create parent container: %v", err)
	}
	defer removeContainer(cli, parentResp.ID)

	if err := cli.ContainerStart(ctx, parentResp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start parent container: %v", err)
	}

	// Create dependent container using parent's network stack
	dependentResp, err := cli.ContainerCreate(ctx,
		&container.Config{
			Image: "alpine:latest",
			Cmd:   []string{"sleep", "300"},
		},
		&container.HostConfig{
			NetworkMode: container.NetworkMode(fmt.Sprintf("container:%s", parentName)),
		},
		nil, nil, dependentName,
	)
	if err != nil {
		t.Fatalf("Failed to create dependent container: %v", err)
	}
	defer removeContainer(cli, dependentResp.ID)

	if err := cli.ContainerStart(ctx, dependentResp.ID, container.StartOptions{}); err != nil {
		t.Fatalf("Failed to start dependent container: %v", err)
	}

	// Inspect parent container
	parentInspect, err := cli.ContainerInspect(ctx, parentResp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect parent container: %v", err)
	}

	// Find dependent containers
	dependents, err := FindDependentContainers(ctx, cli, log, &parentInspect, parentName, parentResp.ID[:12])
	if err != nil {
		t.Fatalf("Failed to find dependent containers: %v", err)
	}

	// Verify dependent found
	if len(dependents) != 1 {
		t.Fatalf("Should find 1 dependent container, got %d", len(dependents))
	}

	if dependents[0].Name != dependentName {
		t.Errorf("Dependent name should be %s, got %s", dependentName, dependents[0].Name)
	}

	// Docker may store NetworkMode with either name or full ID
	expectedByName := fmt.Sprintf("container:%s", parentName)
	expectedByID := fmt.Sprintf("container:%s", parentResp.ID)
	if dependents[0].OldNetworkMode != expectedByName && dependents[0].OldNetworkMode != expectedByID {
		t.Errorf("OldNetworkMode should be container:name or container:id, got %s", dependents[0].OldNetworkMode)
	}

	t.Log("Dependent container detection: OK")
}
