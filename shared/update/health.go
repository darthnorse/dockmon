package update

import (
	"context"
	"fmt"
	"time"

	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// WaitForHealthy waits for a container to become healthy or timeout.
// This function matches the Python backend's health check logic:
// 1. If container has Docker HEALTHCHECK: Poll for "healthy" status
//   - Grace period: min(30s, 50% of timeout) treats "unhealthy" like "starting"
//   - After grace period: "unhealthy" triggers rollback
//
// 2. If no health check: Wait 3s for stability, verify still running
func WaitForHealthy(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	containerID string,
	timeout int,
) error {
	startTime := time.Now()
	deadline := startTime.Add(time.Duration(timeout) * time.Second)
	checkInterval := 2 * time.Second

	// Grace period for containers with health checks: allow "unhealthy" status during startup
	// Use min(30s, 50% of timeout) to handle both short and long timeouts gracefully
	// This matches Python backend behavior in utils/container_health.py
	gracePeriodSeconds := float64(timeout) * 0.5
	if gracePeriodSeconds > 30 {
		gracePeriodSeconds = 30
	}
	gracePeriod := time.Duration(gracePeriodSeconds) * time.Second

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		if time.Now().After(deadline) {
			return fmt.Errorf("health check timeout after %ds", timeout)
		}

		inspect, err := cli.ContainerInspect(ctx, containerID)
		if err != nil {
			return fmt.Errorf("failed to inspect container: %w", err)
		}

		// Check if container is still running
		if !inspect.State.Running {
			return fmt.Errorf("container stopped unexpectedly (exit code: %d)", inspect.State.ExitCode)
		}

		// If no health check defined, wait 3 seconds and assume healthy
		// (matches Python backend behavior)
		if inspect.State.Health == nil {
			log.Debug("No health check defined, waiting 3 seconds for stability")
			select {
			case <-time.After(3 * time.Second):
				// Verify still running after stability wait
				inspect2, err := cli.ContainerInspect(ctx, containerID)
				if err != nil {
					return fmt.Errorf("failed to inspect container after stability wait: %w", err)
				}
				if !inspect2.State.Running {
					return fmt.Errorf("container crashed within 3s of starting (exit code: %d)", inspect2.State.ExitCode)
				}
				log.Info("Container stable after 3s, considering healthy")
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		elapsed := time.Since(startTime)

		switch inspect.State.Health.Status {
		case "healthy":
			log.Info("Container is healthy")
			return nil
		case "unhealthy":
			// Grace period: During initial startup, treat "unhealthy" like "starting"
			// This prevents false negatives for slow-starting containers (e.g., Immich)
			if elapsed < gracePeriod {
				log.Warnf("Container is unhealthy at %.1fs, within %.0fs grace period - continuing to wait",
					elapsed.Seconds(), gracePeriod.Seconds())
			} else {
				// Grace period expired - trust the unhealthy status
				log.Errorf("Container is unhealthy after %.0fs grace period", gracePeriod.Seconds())
				return fmt.Errorf("container is unhealthy")
			}
		case "starting":
			log.Debug("Container health is starting, waiting...")
		default:
			log.Debugf("Unknown health status: %s, waiting...", inspect.State.Health.Status)
		}

		select {
		case <-time.After(checkInterval):
			continue
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}
