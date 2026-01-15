package update

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// FindDependentContainers finds all containers that depend on the given container
// via network_mode: container:X
func FindDependentContainers(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	parentContainer *types.ContainerJSON,
	parentName string,
	parentID string,
) ([]DependentContainer, error) {
	var dependents []DependentContainer

	containers, err := cli.ContainerList(ctx, container.ListOptions{All: true})
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	for _, c := range containers {
		// Skip self
		if c.ID == parentContainer.ID {
			continue
		}

		// Inspect to get full config including NetworkMode
		inspect, err := cli.ContainerInspect(ctx, c.ID)
		if err != nil {
			log.WithError(err).Warnf("Failed to inspect container %s", truncateID(c.ID))
			continue
		}

		networkMode := string(inspect.HostConfig.NetworkMode)

		// Check if this container depends on our parent
		isDependent := networkMode == fmt.Sprintf("container:%s", parentName) ||
			networkMode == fmt.Sprintf("container:%s", parentID) ||
			networkMode == fmt.Sprintf("container:%s", parentContainer.ID)

		if isDependent {
			imageName := inspect.Config.Image
			if imageName == "" && len(inspect.Image) > 0 {
				imageName = inspect.Image
			}

			depName := strings.TrimPrefix(inspect.Name, "/")
			log.Infof("Found dependent container: %s (network_mode: %s)", depName, networkMode)

			dependents = append(dependents, DependentContainer{
				Container:      inspect,
				Name:           depName,
				ID:             truncateID(inspect.ID),
				Image:          imageName,
				OldNetworkMode: networkMode,
			})
		}
	}

	return dependents, nil
}

// RecreateDependentContainers recreates all dependent containers with updated network_mode.
// Returns list of container names that failed to recreate.
func RecreateDependentContainers(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	dependents []DependentContainer,
	newParentID string,
	stopTimeout int,
	isPodman bool,
) []string {
	var failed []string

	for _, dep := range dependents {
		if err := recreateDependentContainer(ctx, cli, log, dep, newParentID, stopTimeout, isPodman); err != nil {
			log.WithError(err).Errorf("Failed to recreate dependent container %s", dep.Name)
			failed = append(failed, dep.Name)
		}
	}

	return failed
}

// recreateDependentContainer recreates a single dependent container with updated network_mode.
func recreateDependentContainer(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	dep DependentContainer,
	newParentID string,
	stopTimeout int,
	isPodman bool,
) error {
	log.Infof("Recreating dependent container: %s", dep.Name)

	// Get labels for filtering (skip for dependents since we don't have old image labels)
	emptyLabels := make(map[string]string)

	// Extract config from dependent container
	extractedConfig, err := ExtractConfig(ctx, cli, log, &dep.Container, dep.Image, emptyLabels, emptyLabels, isPodman)
	if err != nil {
		return fmt.Errorf("failed to extract config: %w", err)
	}

	// Update NetworkMode to point to new parent
	oldNetworkMode := string(extractedConfig.HostConfig.NetworkMode)
	extractedConfig.HostConfig.NetworkMode = container.NetworkMode(fmt.Sprintf("container:%s", newParentID))
	log.Infof("Updated NetworkMode: %s -> container:%s", oldNetworkMode, truncateID(newParentID))

	// Stop dependent container
	log.Debugf("Stopping dependent container: %s", dep.Name)
	stopTimeoutInt := stopTimeout
	if err := cli.ContainerStop(ctx, dep.Container.ID, container.StopOptions{Timeout: &stopTimeoutInt}); err != nil {
		// Try kill if stop fails
		cli.ContainerKill(ctx, dep.Container.ID, "SIGKILL")
	}

	// Rename to temp name
	tempName := fmt.Sprintf("%s-dockmon-temp-%d", dep.Name, time.Now().Unix())
	if err := cli.ContainerRename(ctx, dep.Container.ID, tempName); err != nil {
		return fmt.Errorf("failed to rename to temp: %w", err)
	}

	// Create new dependent container
	newDepResp, err := cli.ContainerCreate(
		ctx,
		extractedConfig.Config,
		extractedConfig.HostConfig,
		nil, // NetworkingConfig not needed for network_mode: container:X
		nil,
		dep.Name,
	)
	if err != nil {
		// Rollback: restore temp container
		cli.ContainerRename(ctx, dep.Container.ID, dep.Name)
		cli.ContainerStart(ctx, dep.Container.ID, container.StartOptions{})
		return fmt.Errorf("failed to create new container: %w", err)
	}
	newDepID := newDepResp.ID

	// Connect additional networks
	if len(extractedConfig.AdditionalNets) > 0 {
		for networkName, endpointConfig := range extractedConfig.AdditionalNets {
			cli.NetworkConnect(ctx, networkName, newDepID, endpointConfig)
		}
	}

	// Start new dependent container
	if err := cli.ContainerStart(ctx, newDepID, container.StartOptions{}); err != nil {
		// Rollback
		cli.ContainerRemove(ctx, newDepID, container.RemoveOptions{Force: true})
		cli.ContainerRename(ctx, dep.Container.ID, dep.Name)
		cli.ContainerStart(ctx, dep.Container.ID, container.StartOptions{})
		return fmt.Errorf("failed to start new container: %w", err)
	}

	// Wait a bit and verify it's running
	time.Sleep(3 * time.Second)
	newInspect, err := cli.ContainerInspect(ctx, newDepID)
	if err != nil || !newInspect.State.Running {
		// Rollback
		stopT := 10
		cli.ContainerStop(ctx, newDepID, container.StopOptions{Timeout: &stopT})
		cli.ContainerRemove(ctx, newDepID, container.RemoveOptions{Force: true})
		cli.ContainerRename(ctx, dep.Container.ID, dep.Name)
		cli.ContainerStart(ctx, dep.Container.ID, container.StartOptions{})
		return fmt.Errorf("new container failed to start properly")
	}

	// Success - remove old temp container
	tempContainer, _ := GetContainerByName(ctx, cli, tempName)
	if tempContainer != "" {
		cli.ContainerRemove(ctx, tempContainer, container.RemoveOptions{Force: true})
	}

	log.Infof("Successfully recreated dependent container: %s (new ID: %s)", dep.Name, truncateID(newDepID))
	return nil
}
