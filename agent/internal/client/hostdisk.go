package client

import (
	"context"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-shared/hostdisk"
	"github.com/sirupsen/logrus"
)

// newHostDiskReader measures the filesystem holding Docker's data-root under
// hostRoot ("" on a systemd host, /hostfs in a container), falling back to the
// host root. The reader itself throttles its warnings.
func newHostDiskReader(dockerClient *docker.Client, hostRoot string, log *logrus.Logger) *hostdisk.Reader {
	var dataRoot func(context.Context) (string, error)
	if dockerClient != nil {
		dataRoot = dockerClient.GetDockerRootDir
	}
	return hostdisk.NewReader(hostdisk.NewProber(hostRoot), dataRoot, log.Warnf)
}

// warnIfHostRootUnmounted says once at startup why a containerized agent will
// report no disk. A directory at /hostfs that is not a mount counts as absent:
// probing it would report the container's own disk as the host's.
func warnIfHostRootUnmounted(log *logrus.Logger) {
	mounted, err := hostdisk.NewProber(hostdisk.DefaultHostRoot).HostRootMounted()
	if err != nil {
		log.Warnf("Could not verify the %s mount (%v); host disk usage will not be reported", hostdisk.DefaultHostRoot, err)
		return
	}
	if !mounted {
		log.Warnf("Host disk usage disabled: %s is not mounted. Host disk_percent alerts cannot fire. "+
			"Add -v /:/hostfs:ro to the agent container.", hostdisk.DefaultHostRoot)
	}
}
