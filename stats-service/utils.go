package main

import (
	dockerpkg "github.com/darthnorse/dockmon-shared/docker"
)

// truncateID is now a wrapper for the shared package implementation
func truncateID(id string, length int) string {
	return dockerpkg.TruncateID(id, length)
}
