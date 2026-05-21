package update

import (
	"context"
	"fmt"
	"strings"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// ExtractConfig extracts container configuration for recreation with a new image.
//
// SHALLOW COPY SAFETY NOTE:
// Go struct copy creates a shallow copy where pointer fields point to the same
// underlying data. This is SAFE because:
// 1. We do NOT modify the original config after copying
// 2. The original container is being destroyed anyway
// 3. We only REPLACE pointer fields, never mutate their contents
func ExtractConfig(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	inspect *types.ContainerJSON,
	newImage string,
	oldImageLabels map[string]string,
	newImageLabels map[string]string,
	oldImageEnv []string,
	isPodman bool,
) (*ExtractedConfig, error) {

	// STRUCT COPY - preserves ALL fields including DeviceRequests, Healthcheck, Tmpfs, etc.
	newConfig := *inspect.Config
	newConfig.Image = newImage

	// STRUCT COPY - preserves ALL fields including DeviceRequests, Resources, etc.
	newHostConfig := *inspect.HostConfig

	// Apply Podman compatibility fixes
	if isPodman {
		applyPodmanFixes(log, &newHostConfig)
	}

	// Handle container:X network mode
	// When sharing another container's network namespace, this container cannot have:
	// - Hostname/Domainname/MacAddress (network identity belongs to parent)
	// - PortBindings/ExposedPorts (ports are managed by parent container)
	// Docker API 1.47+ rejects containers with both network_mode:container:X and port bindings
	networkMode := string(newHostConfig.NetworkMode)
	if strings.HasPrefix(networkMode, "container:") {
		newConfig.Hostname = ""
		newConfig.Domainname = ""
		newConfig.MacAddress = ""
		newConfig.ExposedPorts = nil
		newHostConfig.PortBindings = nil
		log.Debug("Cleared Hostname/Domainname/MacAddress/Ports for container: network mode")
	}

	// Resolve NetworkMode container:ID -> container:name
	if err := resolveNetworkMode(ctx, cli, log, &newHostConfig); err != nil {
		log.WithError(err).Warn("Failed to resolve NetworkMode, using as-is")
	}

	// Extract user-added labels (filter out old image labels)
	userLabels := ExtractUserLabels(log, newConfig.Labels, oldImageLabels)
	newConfig.Labels = userLabels

	// Extract user-added/modified env vars (filter out old image ENV defaults).
	// Without this, env vars inherited from the old image become per-container
	// overrides that shadow the new image's ENV directives.
	newConfig.Env = ExtractUserEnv(log, newConfig.Env, oldImageEnv)

	// Extract network configuration
	primaryNetConfig, additionalNetworks := extractNetworkConfig(log, inspect)

	containerName := strings.TrimPrefix(inspect.Name, "/")

	return &ExtractedConfig{
		Config:           &newConfig,
		HostConfig:       &newHostConfig,
		NetworkingConfig: primaryNetConfig,
		AdditionalNets:   additionalNetworks,
		ContainerName:    containerName,
	}, nil
}

// applyPodmanFixes modifies HostConfig for Podman compatibility.
func applyPodmanFixes(log *logrus.Logger, hostConfig *container.HostConfig) {
	// Fix 1: NanoCpus -> CpuQuota/CpuPeriod
	if hostConfig.NanoCPUs > 0 && hostConfig.CPUPeriod == 0 {
		cpuPeriod := int64(100000)
		cpuQuota := int64(float64(hostConfig.NanoCPUs) / 1e9 * float64(cpuPeriod))
		hostConfig.CPUPeriod = cpuPeriod
		hostConfig.CPUQuota = cpuQuota
		hostConfig.NanoCPUs = 0
		log.Debug("Converted NanoCpus to CpuQuota/CpuPeriod for Podman")
	}

	// Fix 2: Remove MemorySwappiness for Podman
	if hostConfig.Resources.MemorySwappiness != nil {
		hostConfig.Resources.MemorySwappiness = nil
		log.Debug("Removed MemorySwappiness for Podman compatibility")
	}
}

// resolveNetworkMode converts container:ID to container:name in NetworkMode.
func resolveNetworkMode(
	ctx context.Context,
	cli *client.Client,
	log *logrus.Logger,
	hostConfig *container.HostConfig,
) error {
	networkMode := string(hostConfig.NetworkMode)
	if !strings.HasPrefix(networkMode, "container:") {
		return nil
	}

	refID := strings.TrimPrefix(networkMode, "container:")

	refContainer, err := cli.ContainerInspect(ctx, refID)
	if err != nil {
		return fmt.Errorf("failed to resolve container reference %s: %w", refID, err)
	}

	refName := strings.TrimPrefix(refContainer.Name, "/")
	hostConfig.NetworkMode = container.NetworkMode("container:" + refName)
	log.Debugf("Resolved NetworkMode to container:%s", refName)

	return nil
}

// ExtractUserLabels filters container labels to preserve only user-added labels.
// Removes labels that came from the OLD image so new image labels can take effect.
// Exported so the agent self-update path can reuse the same filtering logic.
func ExtractUserLabels(
	log *logrus.Logger,
	containerLabels map[string]string,
	oldImageLabels map[string]string,
) map[string]string {
	if containerLabels == nil {
		return make(map[string]string)
	}

	userLabels := make(map[string]string)
	for key, containerValue := range containerLabels {
		// Keep label if:
		// 1. It doesn't exist in old image labels (user added it), OR
		// 2. Its value differs from old image (user modified it)
		imageValue, existsInImage := oldImageLabels[key]
		if !existsInImage || containerValue != imageValue {
			userLabels[key] = containerValue
		}
	}

	log.Debugf("Label filtering: %d container - %d image defaults = %d user labels preserved",
		len(containerLabels), len(oldImageLabels), len(userLabels))

	return userLabels
}

// ExtractUserEnv filters container env vars to preserve only user-added or
// user-modified entries. Removes entries that exactly match the OLD image's
// ENV defaults so the NEW image's ENV directives can take effect on update.
//
// Docker's container inspect returns the merged effective env (image defaults
// + user-set), so without filtering, every image default becomes a per-
// container override that shadows the new image on recreate.
//
// Known trade-off: if a user explicitly sets an env var to exactly the same
// value as the old image's default (e.g. `-e APP_VERSION=v3.0.0` against an
// image whose ENV already says `APP_VERSION=v3.0.0`), we cannot distinguish
// that from inheritance and the entry is dropped. On update, the new image's
// value wins. This matches `docker compose up -d` semantics, where env vars
// not in the compose file come from the new image.
//
// Parsing: each entry is split on the FIRST '=' only via strings.Cut, so
// values containing '=' (e.g. DATABASE_URL=postgres://u:p=hash@host) are
// preserved correctly. Entries with no '=' are kept as-is defensively.
func ExtractUserEnv(
	log *logrus.Logger,
	containerEnv []string,
	oldImageEnv []string,
) []string {
	if containerEnv == nil {
		return []string{}
	}

	imageDefaults := make(map[string]string, len(oldImageEnv))
	for _, entry := range oldImageEnv {
		if key, value, ok := strings.Cut(entry, "="); ok {
			imageDefaults[key] = value
		}
	}

	userEnv := make([]string, 0, len(containerEnv))
	for _, entry := range containerEnv {
		key, value, ok := strings.Cut(entry, "=")
		if !ok {
			// Malformed (no '='): keep defensively, don't crash.
			userEnv = append(userEnv, entry)
			continue
		}
		// Keep if user added (not in image) OR user modified (different value).
		if imageValue, existsInImage := imageDefaults[key]; !existsInImage || value != imageValue {
			userEnv = append(userEnv, entry)
		}
	}

	log.Debugf("Env filtering: %d container - %d image defaults = %d user env preserved",
		len(containerEnv), len(oldImageEnv), len(userEnv))

	return userEnv
}

// extractNetworkConfig extracts network configuration from container.
func extractNetworkConfig(
	log *logrus.Logger,
	inspect *types.ContainerJSON,
) (*network.NetworkingConfig, map[string]*network.EndpointSettings) {

	if inspect.NetworkSettings == nil || inspect.NetworkSettings.Networks == nil {
		return nil, nil
	}

	networks := inspect.NetworkSettings.Networks
	networkMode := string(inspect.HostConfig.NetworkMode)

	// Handle special network modes - no network config needed
	if strings.HasPrefix(networkMode, "container:") || networkMode == "host" || networkMode == "none" {
		return nil, nil
	}

	// Filter to custom networks only (exclude bridge, host, none)
	customNetworks := make(map[string]*network.EndpointSettings)
	for name, data := range networks {
		if name != "bridge" && name != "host" && name != "none" {
			customNetworks[name] = data
		}
	}

	if len(customNetworks) == 0 {
		return nil, nil
	}

	// Determine primary network
	primaryNetwork := networkMode
	if primaryNetwork == "" || primaryNetwork == "default" {
		primaryNetwork = "bridge"
	}
	// If NetworkMode doesn't match a network name, use first custom network
	if _, exists := customNetworks[primaryNetwork]; !exists && len(customNetworks) > 0 {
		for name := range customNetworks {
			primaryNetwork = name
			break
		}
	}

	var primaryNetConfig *network.NetworkingConfig
	additionalNetworks := make(map[string]*network.EndpointSettings)

	for networkName, networkData := range customNetworks {
		endpointConfig := buildEndpointConfig(networkData)

		if networkName == primaryNetwork {
			hasConfig := endpointConfig.IPAMConfig != nil ||
				len(endpointConfig.Aliases) > 0 ||
				len(endpointConfig.Links) > 0

			if hasConfig {
				primaryNetConfig = &network.NetworkingConfig{
					EndpointsConfig: map[string]*network.EndpointSettings{
						networkName: endpointConfig,
					},
				}
				log.Debugf("Primary network %s has static config (IP/aliases/links)", networkName)
			}
		} else {
			additionalNetworks[networkName] = endpointConfig
		}
	}

	if len(additionalNetworks) == 0 {
		additionalNetworks = nil
	} else {
		log.Debugf("Extracted %d additional networks for post-creation connection", len(additionalNetworks))
	}

	return primaryNetConfig, additionalNetworks
}

// buildEndpointConfig creates an EndpointSettings with user-configured values only.
func buildEndpointConfig(data *network.EndpointSettings) *network.EndpointSettings {
	endpoint := &network.EndpointSettings{}

	// Extract IPAM config (static IPs)
	if data.IPAMConfig != nil {
		ipam := &network.EndpointIPAMConfig{}
		if data.IPAMConfig.IPv4Address != "" {
			ipam.IPv4Address = data.IPAMConfig.IPv4Address
		}
		if data.IPAMConfig.IPv6Address != "" {
			ipam.IPv6Address = data.IPAMConfig.IPv6Address
		}
		if ipam.IPv4Address != "" || ipam.IPv6Address != "" {
			endpoint.IPAMConfig = ipam
		}
	}

	// Filter aliases - remove auto-generated short ID (12 chars)
	if len(data.Aliases) > 0 {
		var userAliases []string
		for _, alias := range data.Aliases {
			if len(alias) != 12 {
				userAliases = append(userAliases, alias)
			}
		}
		if len(userAliases) > 0 {
			endpoint.Aliases = userAliases
		}
	}

	// Preserve links
	if len(data.Links) > 0 {
		endpoint.Links = data.Links
	}

	return endpoint
}

// GetImageLabels returns the labels defined in an image.
func GetImageLabels(ctx context.Context, cli *client.Client, imageRef string) (map[string]string, error) {
	img, _, err := cli.ImageInspectWithRaw(ctx, imageRef)
	if err != nil {
		return nil, fmt.Errorf("failed to inspect image: %w", err)
	}

	if img.Config == nil || img.Config.Labels == nil {
		return make(map[string]string), nil
	}

	return img.Config.Labels, nil
}

// GetImageEnv returns the env vars defined in an image's ENV directives.
func GetImageEnv(ctx context.Context, cli *client.Client, imageRef string) ([]string, error) {
	img, _, err := cli.ImageInspectWithRaw(ctx, imageRef)
	if err != nil {
		return nil, fmt.Errorf("failed to inspect image: %w", err)
	}

	if img.Config == nil || img.Config.Env == nil {
		return []string{}, nil
	}

	return img.Config.Env, nil
}
