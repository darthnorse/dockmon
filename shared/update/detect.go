package update

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// DetectOptions detects runtime options (Podman, API version) from Docker daemon.
// Returns options that can be passed to NewUpdater.
func DetectOptions(ctx context.Context, cli *client.Client, log *logrus.Logger) UpdaterOptions {
	options := UpdaterOptions{}

	// Detect Podman
	isPodman, err := detectPodman(ctx, cli)
	if err != nil {
		log.WithError(err).Warn("Failed to detect Podman, assuming Docker")
	}
	options.IsPodman = isPodman

	if isPodman {
		log.Info("Detected Podman runtime - will apply compatibility fixes")
	}

	// Detect API version for networking_config support
	supportsNetworkingConfig, err := detectNetworkingConfigSupport(ctx, cli)
	if err != nil {
		log.WithError(err).Warn("Failed to detect API version, assuming legacy mode")
	}
	options.SupportsNetworkingConfig = supportsNetworkingConfig

	apiVersion, _ := getAPIVersion(ctx, cli)
	if supportsNetworkingConfig {
		log.Infof("Docker API %s supports networking_config at creation", apiVersion)
	} else {
		log.Infof("Docker API %s requires manual network connection (legacy mode)", apiVersion)
	}

	return options
}

// detectPodman returns true if connected to Podman instead of Docker.
func detectPodman(ctx context.Context, cli *client.Client) (bool, error) {
	info, err := cli.Info(ctx)
	if err != nil {
		return false, fmt.Errorf("failed to get Docker info: %w", err)
	}

	// Check multiple indicators for reliability:
	// 1. Operating system contains "podman"
	osLower := strings.ToLower(info.OperatingSystem)
	if strings.Contains(osLower, "podman") {
		return true, nil
	}

	// 2. Server version components contain "podman"
	version, err := cli.ServerVersion(ctx)
	if err == nil {
		for _, comp := range version.Components {
			if strings.ToLower(comp.Name) == "podman" {
				return true, nil
			}
		}
	}

	return false, nil
}

// detectNetworkingConfigSupport returns true if API >= 1.44 (can set network at creation).
func detectNetworkingConfigSupport(ctx context.Context, cli *client.Client) (bool, error) {
	apiVersion, err := getAPIVersion(ctx, cli)
	if err != nil {
		return false, err
	}

	// Parse version string (e.g., "1.44" -> major=1, minor=44)
	parts := strings.Split(apiVersion, ".")
	if len(parts) < 2 {
		return false, fmt.Errorf("invalid API version format: %s", apiVersion)
	}

	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return false, fmt.Errorf("invalid major version: %s", parts[0])
	}

	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		return false, fmt.Errorf("invalid minor version: %s", parts[1])
	}

	// API >= 1.44 supports networking_config at creation
	if major > 1 || (major == 1 && minor >= 44) {
		return true, nil
	}

	return false, nil
}

// getAPIVersion returns the Docker API version string.
func getAPIVersion(ctx context.Context, cli *client.Client) (string, error) {
	version, err := cli.ServerVersion(ctx)
	if err != nil {
		return "", fmt.Errorf("failed to get server version: %w", err)
	}
	return version.APIVersion, nil
}
