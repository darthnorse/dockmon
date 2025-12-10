package compose

import (
	"context"
	"fmt"
	"strings"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// DiscoverContainers finds containers created by compose for a given project
func DiscoverContainers(
	ctx context.Context,
	dockerClient *client.Client,
	projectName string,
	log *logrus.Logger,
) (map[string]ServiceResult, error) {
	// Filter by compose project label
	filterArgs := filters.NewArgs()
	filterArgs.Add("label", fmt.Sprintf("com.docker.compose.project=%s", projectName))

	containers, err := dockerClient.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filterArgs,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	services := make(map[string]ServiceResult)

	for _, c := range containers {
		serviceName := c.Labels["com.docker.compose.service"]
		if serviceName == "" {
			serviceName = "unknown"
		}

		containerName := ""
		if len(c.Names) > 0 {
			containerName = strings.TrimPrefix(c.Names[0], "/")
		}

		// CRITICAL: Always use short ID (12 chars) per CLAUDE.md
		shortID := c.ID
		if len(shortID) > 12 {
			shortID = shortID[:12]
		}

		// Use c.Status which includes health info (e.g., "Up 9 minutes (unhealthy)")
		// c.State only contains basic state like "running" without health details
		status := c.Status
		if status == "" {
			status = c.State
		}

		services[serviceName] = ServiceResult{
			ContainerID:   shortID,
			ContainerName: containerName,
			Image:         c.Image,
			Status:        status,
		}

		if log != nil {
			log.WithFields(logrus.Fields{
				"service":      serviceName,
				"container_id": shortID,
				"name":         containerName,
				"status":       status,
			}).Debug("Discovered compose service")
		}
	}

	return services, nil
}

// DiscoverContainersWithTypes finds containers and returns full Docker types
// Used when we need more container details than ServiceResult provides
func DiscoverContainersWithTypes(
	ctx context.Context,
	dockerClient *client.Client,
	projectName string,
) ([]types.Container, error) {
	filterArgs := filters.NewArgs()
	filterArgs.Add("label", fmt.Sprintf("com.docker.compose.project=%s", projectName))

	return dockerClient.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filterArgs,
	})
}

// AnalyzeServiceStatus checks each service and determines success/partial/failure
func AnalyzeServiceStatus(
	deploymentID string,
	services map[string]ServiceResult,
	log *logrus.Logger,
) *DeployResult {
	var runningServices []string
	var failedServices []string
	var failedErrors []string

	for serviceName, service := range services {
		if IsServiceHealthy(service.Status) {
			runningServices = append(runningServices, serviceName)
		} else {
			failedServices = append(failedServices, serviceName)
			errMsg := fmt.Sprintf("%s: %s", serviceName, service.Status)
			if service.Error != "" {
				errMsg = fmt.Sprintf("%s: %s (%s)", serviceName, service.Status, service.Error)
			}
			failedErrors = append(failedErrors, errMsg)
		}
	}

	// All services running
	if len(failedServices) == 0 && len(runningServices) > 0 {
		if log != nil {
			log.WithFields(logrus.Fields{
				"deployment_id":  deploymentID,
				"services_count": len(services),
			}).Info("Compose deployment completed successfully - all services running")
		}

		return &DeployResult{
			DeploymentID: deploymentID,
			Success:      true,
			Services:     services,
		}
	}

	// Partial success
	if len(runningServices) > 0 && len(failedServices) > 0 {
		if log != nil {
			log.WithFields(logrus.Fields{
				"deployment_id":    deploymentID,
				"running_services": runningServices,
				"failed_services":  failedServices,
			}).Warn("Compose deployment partial success - some services failed")
		}

		errorMsg := fmt.Sprintf("Partial deployment: %d/%d services running. Failed: %s",
			len(runningServices), len(services), strings.Join(failedErrors, "; "))

		return &DeployResult{
			DeploymentID:   deploymentID,
			Success:        false,
			PartialSuccess: true,
			Services:       services,
			FailedServices: failedServices,
			Error:          NewInternalError(errorMsg),
		}
	}

	// All failed
	if len(runningServices) == 0 && len(failedServices) > 0 {
		if log != nil {
			log.WithFields(logrus.Fields{
				"deployment_id":   deploymentID,
				"failed_services": failedServices,
			}).Error("Compose deployment failed - no services running")
		}

		errorMsg := fmt.Sprintf("All services failed to start: %s", strings.Join(failedErrors, "; "))

		return &DeployResult{
			DeploymentID:   deploymentID,
			Success:        false,
			PartialSuccess: false,
			Services:       services,
			FailedServices: failedServices,
			Error:          NewInternalError(errorMsg),
		}
	}

	// No services (shouldn't happen)
	if log != nil {
		log.WithField("deployment_id", deploymentID).Warn("No services discovered after compose up")
	}
	return &DeployResult{
		DeploymentID: deploymentID,
		Success:      true,
		Services:     services,
	}
}
