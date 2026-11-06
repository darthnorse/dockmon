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
	dependents, _, err := findDependents(ctx, cli, log, parentContainer, parentName, parentID)
	return dependents, err
}

// findDependents also returns the names of containers it could not inspect, so
// recovery can report them rather than silently skip a possible dependent.
func findDependents(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	parentContainer *types.ContainerJSON,
	parentName string,
	parentID string,
) ([]DependentContainer, []string, error) {
	var dependents []DependentContainer
	var uninspectable []string

	containers, err := cli.ContainerList(ctx, container.ListOptions{All: true})
	if err != nil {
		return nil, nil, fmt.Errorf("failed to list containers: %w", err)
	}

	dependsOn := func(networkMode string) bool {
		return networkMode == fmt.Sprintf("container:%s", parentName) ||
			networkMode == fmt.Sprintf("container:%s", parentID) ||
			networkMode == fmt.Sprintf("container:%s", parentContainer.ID)
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
			if !client.IsErrNotFound(err) && dependsOn(c.HostConfig.NetworkMode) {
				uninspectable = append(uninspectable, summaryName(c))
			}
			continue
		}

		networkMode := string(inspect.HostConfig.NetworkMode)

		if dependsOn(networkMode) {
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

	return dependents, uninspectable, nil
}

func summaryName(c types.Container) string {
	if len(c.Names) > 0 {
		return strings.TrimPrefix(c.Names[0], "/")
	}
	return truncateID(c.ID)
}

func isDependentRunning(dep DependentContainer) bool {
	return dep.Container.ContainerJSONBase != nil &&
		dep.Container.State != nil &&
		dep.Container.State.Running
}

func runningDependents(dependents []DependentContainer) []DependentContainer {
	var running []DependentContainer
	for _, dep := range dependents {
		if isDependentRunning(dep) {
			running = append(running, dep)
		}
	}
	return running
}

func runningDependentNames(dependents []DependentContainer) []string {
	var names []string
	for _, dep := range runningDependents(dependents) {
		names = append(names, dep.Name)
	}
	return names
}

// RecoverDependents restarts dependents of a provider that was stopped and
// restored under the same ID. Docker does not reconnect them: they keep running
// with loopback only until restarted. Returns the names of dependents that were
// not recovered.
//
// captured is the list from before the provider stopped. It is reconciled with a
// fresh lookup so that dependents created since are included, and those that
// exited when their network went away are not mistaken for deliberately stopped.
func RecoverDependents(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	captured []DependentContainer,
	providerID string,
	providerName string,
	stopTimeout int,
) []string {
	provider, err := cli.ContainerInspect(ctx, providerID)
	if err != nil {
		log.WithError(err).Errorf("Cannot inspect restored provider %s, dependents not recovered", providerName)
		return runningDependentNames(captured)
	}

	toRestart, notRecovered := dependentsToRestart(ctx, cli, log, captured, &provider, providerName, providerID)

	if provider.State == nil || !provider.State.Running {
		for _, dep := range toRestart {
			log.Warnf("Dependent %s has no network and cannot be restarted while provider %s is stopped", dep.Name, providerName)
			notRecovered = append(notRecovered, dep.Name)
		}
		return notRecovered
	}

	for _, dep := range toRestart {
		if err := cli.ContainerRestart(ctx, dep.Container.ID, container.StopOptions{Timeout: &stopTimeout}); err != nil {
			log.WithError(err).Errorf("Failed to restart dependent %s after rollback", dep.Name)
			notRecovered = append(notRecovered, dep.Name)
			continue
		}
		log.Infof("Restarted dependent %s after rollback of %s", dep.Name, providerName)
	}
	return notRecovered
}

func dependentsToRestart(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	captured []DependentContainer,
	provider *types.ContainerJSON,
	providerName string,
	providerID string,
) ([]DependentContainer, []string) {
	current, uninspectable, err := findDependents(ctx, cli, log, provider, providerName, providerID)
	if err != nil {
		log.WithError(err).Warnf("Cannot look up dependents of %s, using the list from before the update", providerName)
		return runningDependents(captured), nil
	}

	wasRunning := make(map[string]bool, len(captured))
	for _, dep := range captured {
		wasRunning[dep.Container.ID] = isDependentRunning(dep)
	}

	var toRestart []DependentContainer
	for _, dep := range current {
		if isDependentRunning(dep) || wasRunning[dep.Container.ID] {
			toRestart = append(toRestart, dep)
		}
	}
	return toRestart, uninspectable
}

// RecreateDependentContainers recreates all dependent containers with updated network_mode.
// Dependents that were stopped stay stopped, and none can start while the provider
// is stopped. Returns the names that failed to recreate, plus those left stopped
// only because the provider is stopped.
func RecreateDependentContainers(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	dependents []DependentContainer,
	newParentID string,
	providerRunning bool,
	stopTimeout int,
	isPodman bool,
) []string {
	var failed []string

	for _, dep := range dependents {
		wasRunning := isDependentRunning(dep)
		if err := recreateDependentContainer(ctx, cli, log, dep, newParentID, wasRunning && providerRunning, stopTimeout, isPodman); err != nil {
			log.WithError(err).Errorf("Failed to recreate dependent container %s", dep.Name)
			failed = append(failed, dep.Name)
			continue
		}
		if wasRunning && !providerRunning {
			log.Warnf("Dependent %s left stopped because its provider is stopped", dep.Name)
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
	startAfterCreate bool,
	stopTimeout int,
	isPodman bool,
) error {
	log.Infof("Recreating dependent container: %s", dep.Name)

	// Skip label and env filtering for dependents: we're not updating their
	// image, just rewiring NetworkMode to the new parent, so inherited values
	// should pass through verbatim.
	emptyLabels := make(map[string]string)

	// Extract config from dependent container
	extractedConfig, err := ExtractConfig(ctx, cli, log, &dep.Container, dep.Image, emptyLabels, emptyLabels, nil, isPodman)
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
		restoreOldDependent(ctx, cli, dep)
		return fmt.Errorf("failed to create new container: %w", err)
	}
	newDepID := newDepResp.ID

	// Connect additional networks
	if len(extractedConfig.AdditionalNets) > 0 {
		for networkName, endpointConfig := range extractedConfig.AdditionalNets {
			cli.NetworkConnect(ctx, networkName, newDepID, endpointConfig)
		}
	}

	if !startAfterCreate {
		cli.ContainerRemove(ctx, dep.Container.ID, container.RemoveOptions{Force: true})
		log.Infof("Recreated dependent container %s without starting it (new ID: %s)", dep.Name, truncateID(newDepID))
		return nil
	}

	// Start new dependent container
	if err := cli.ContainerStart(ctx, newDepID, container.StartOptions{}); err != nil {
		cli.ContainerRemove(ctx, newDepID, container.RemoveOptions{Force: true})
		restoreOldDependent(ctx, cli, dep)
		return fmt.Errorf("failed to start new container: %w", err)
	}

	// Wait a bit and verify it's running
	time.Sleep(3 * time.Second)
	newInspect, err := cli.ContainerInspect(ctx, newDepID)
	if err != nil || !newInspect.State.Running {
		stopT := 10
		cli.ContainerStop(ctx, newDepID, container.StopOptions{Timeout: &stopT})
		cli.ContainerRemove(ctx, newDepID, container.RemoveOptions{Force: true})
		restoreOldDependent(ctx, cli, dep)
		return fmt.Errorf("new container failed to start properly")
	}

	cli.ContainerRemove(ctx, dep.Container.ID, container.RemoveOptions{Force: true})

	log.Infof("Successfully recreated dependent container: %s (new ID: %s)", dep.Name, truncateID(newDepID))
	return nil
}

func restoreOldDependent(ctx context.Context, cli *client.Client, dep DependentContainer) {
	cli.ContainerRename(ctx, dep.Container.ID, dep.Name)
	if isDependentRunning(dep) {
		cli.ContainerStart(ctx, dep.Container.ID, container.StartOptions{})
	}
}
