package update

import (
	"context"
	"fmt"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// CreateBackup stops the container and renames it to a backup name.
// Returns the backup name for later restoration or cleanup.
func CreateBackup(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	containerID string,
	containerName string,
	stopTimeout int,
) (string, error) {
	backupName := fmt.Sprintf("%s-dockmon-backup-%d", containerName, time.Now().Unix())

	// Stop container gracefully
	log.Debugf("Stopping container %s", truncateID(containerID))
	stopTimeoutInt := stopTimeout
	if err := cli.ContainerStop(ctx, containerID, container.StopOptions{Timeout: &stopTimeoutInt}); err != nil {
		log.WithError(err).Warn("Failed to stop container gracefully, continuing with rename")
	}

	// Rename to backup name to free the original name
	log.Debugf("Renaming container to backup: %s", backupName)
	if err := cli.ContainerRename(ctx, containerID, backupName); err != nil {
		return "", fmt.Errorf("failed to rename container to backup: %w", err)
	}

	log.Infof("Created backup: %s (original: %s)", backupName, containerName)
	return backupName, nil
}

// RestoreBackup restores the backup container to its original name and starts it.
func RestoreBackup(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	backupName string,
	originalName string,
) {
	log.Warnf("Restoring backup %s to %s", backupName, originalName)

	// Find backup container
	backupID, err := GetContainerByName(ctx, cli, backupName)
	if err != nil || backupID == "" {
		log.WithError(err).Errorf("CRITICAL: Failed to find backup container %s", backupName)
		return
	}

	// Inspect backup to check its state
	backupInspect, err := cli.ContainerInspect(ctx, backupID)
	if err != nil {
		log.WithError(err).Errorf("Failed to inspect backup container %s", backupName)
		return
	}

	// Handle various backup states
	backupStatus := backupInspect.State.Status
	log.Infof("Backup container %s status: %s", backupName, backupStatus)

	switch backupStatus {
	case "running":
		log.Warn("Backup is running (unexpected), stopping first")
		stopTimeout := 10
		if err := cli.ContainerStop(ctx, backupID, container.StopOptions{Timeout: &stopTimeout}); err != nil {
			cli.ContainerKill(ctx, backupID, "SIGKILL")
		}
	case "restarting", "dead":
		log.Warnf("Backup in %s state, killing", backupStatus)
		cli.ContainerKill(ctx, backupID, "SIGKILL")
	}

	// Remove any container with the original name (failed new container)
	existingID, _ := GetContainerByName(ctx, cli, originalName)
	if existingID != "" {
		log.Debugf("Removing failed container %s to restore backup", truncateID(existingID))
		cli.ContainerRemove(ctx, existingID, container.RemoveOptions{Force: true})
	}

	// Rename backup to original name
	if err := cli.ContainerRename(ctx, backupID, originalName); err != nil {
		log.WithError(err).Errorf("CRITICAL: Failed to rename backup to %s", originalName)
		return
	}

	// Start the restored container
	if err := cli.ContainerStart(ctx, backupID, container.StartOptions{}); err != nil {
		log.WithError(err).Errorf("CRITICAL: Failed to start restored container %s", originalName)
		return
	}

	log.Warnf("Successfully restored backup to %s", originalName)
}

// RemoveBackup removes the backup container after successful update.
func RemoveBackup(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	backupName string,
) {
	backupID, err := GetContainerByName(ctx, cli, backupName)
	if err != nil || backupID == "" {
		log.WithError(err).Warnf("Backup container %s not found for cleanup", backupName)
		return
	}

	if err := cli.ContainerRemove(ctx, backupID, container.RemoveOptions{Force: true}); err != nil {
		log.WithError(err).Warnf("Failed to remove backup container %s", backupName)
	} else {
		log.Infof("Removed backup container %s", backupName)
	}
}

// GetContainerByName finds a container by name and returns its ID.
// Returns empty string if not found.
func GetContainerByName(ctx context.Context, cli *client.Client, name string) (string, error) {
	containers, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", "^/"+name+"$")),
	})
	if err != nil {
		return "", fmt.Errorf("failed to list containers: %w", err)
	}

	if len(containers) == 0 {
		return "", nil
	}

	return containers[0].ID, nil
}

// truncateID truncates a container ID to 12 characters.
func truncateID(id string) string {
	if len(id) >= 12 {
		return id[:12]
	}
	return id
}
