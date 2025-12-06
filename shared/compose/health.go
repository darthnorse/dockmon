package compose

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/docker/compose/v2/pkg/api"
	"github.com/sirupsen/logrus"
)

// WaitForHealthy polls container status until all are healthy or timeout
func WaitForHealthy(
	ctx context.Context,
	composeService api.Compose,
	projectName string,
	timeoutSecs int,
	log *logrus.Logger,
	progressFn ProgressCallback,
) error {
	if log != nil {
		log.WithFields(logrus.Fields{
			"project_name": projectName,
			"timeout_secs": timeoutSecs,
		}).Info("Waiting for services to be healthy")
	}

	deadline := time.Now().Add(time.Duration(timeoutSecs) * time.Second)
	pollInterval := 2 * time.Second

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// Get container status via compose ps
		containers, err := composeService.Ps(ctx, projectName, api.PsOptions{All: true})
		if err != nil {
			if log != nil {
				log.WithField("error", err.Error()).Debug("Failed to get container status, retrying...")
			}
			time.Sleep(pollInterval)
			continue
		}

		if len(containers) == 0 {
			if log != nil {
				log.Debug("No containers found yet, retrying...")
			}
			time.Sleep(pollInterval)
			continue
		}

		// Check health status
		allHealthy := true
		var unhealthyServices []string

		for _, c := range containers {
			healthy := IsContainerHealthy(c)
			if !healthy {
				allHealthy = false
				unhealthyServices = append(unhealthyServices, c.Service)
			}
		}

		if allHealthy {
			if log != nil {
				log.WithField("container_count", len(containers)).Info("All services are healthy")
			}
			return nil
		}

		if log != nil {
			log.WithFields(logrus.Fields{
				"unhealthy_services": unhealthyServices,
				"total_services":     len(containers),
			}).Debug("Waiting for services to be healthy...")
		}

		// Send progress update
		if progressFn != nil {
			progressFn(ProgressEvent{
				Stage:    StageHealthCheck,
				Progress: 92,
				Message:  fmt.Sprintf("Waiting for %d service(s) to be healthy...", len(unhealthyServices)),
			})
		}

		time.Sleep(pollInterval)
	}

	// Timeout - get final status
	containers, _ := composeService.Ps(ctx, projectName, api.PsOptions{All: true})
	var unhealthyDetails []string
	for _, c := range containers {
		if !IsContainerHealthy(c) {
			detail := fmt.Sprintf("%s: state=%s, health=%s", c.Service, c.State, c.Health)
			unhealthyDetails = append(unhealthyDetails, detail)
		}
	}

	return fmt.Errorf("timeout after %d seconds waiting for healthy services. Unhealthy: %s",
		timeoutSecs, strings.Join(unhealthyDetails, "; "))
}

// IsContainerHealthy checks if a container is healthy
func IsContainerHealthy(c api.ContainerSummary) bool {
	state := strings.ToLower(c.State)
	health := strings.ToLower(c.Health)

	// If container has a health check
	if health != "" {
		return health == "healthy"
	}

	// No health check - just check if running
	return state == "running"
}

// IsServiceHealthy checks if a service status indicates healthy/running state
func IsServiceHealthy(status string) bool {
	status = strings.ToLower(status)
	if status == "running" || status == "up" || strings.HasPrefix(status, "up ") {
		return true
	}
	if strings.Contains(status, "healthy") && !strings.Contains(status, "unhealthy") {
		return true
	}
	return false
}
