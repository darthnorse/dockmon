package compose

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/sirupsen/logrus"
)

const (
	// TempDirName is the name of the compose temp directory
	TempDirName = "dockmon-compose"
	// TempFilePrefix is the prefix for temp compose files
	TempFilePrefix = "compose-"
	// TempFileMode is the file permission for temp files (owner read/write only)
	TempFileMode os.FileMode = 0600
	// TempDirMode is the directory permission for temp directory (owner only)
	TempDirMode os.FileMode = 0700
	// StaleFileThreshold is how old a temp file must be to be cleaned up
	StaleFileThreshold = 1 * time.Hour
)

var tempDir string

func init() {
	// Create dedicated temp directory on package init
	tempDir = filepath.Join(os.TempDir(), TempDirName)
	_ = os.MkdirAll(tempDir, TempDirMode)
}

// GetTempDir returns the compose temp directory path
func GetTempDir() string {
	return tempDir
}

// WriteComposeFile writes compose content to a secure temp file
// Returns the path to the temp file. Caller is responsible for cleanup.
func WriteComposeFile(content string) (string, error) {
	// Ensure temp dir exists with proper permissions
	if err := os.MkdirAll(tempDir, TempDirMode); err != nil {
		return "", fmt.Errorf("failed to create temp dir: %w", err)
	}

	f, err := os.CreateTemp(tempDir, TempFilePrefix+"*.yml")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file: %w", err)
	}

	// Ensure restrictive permissions
	if err := f.Chmod(TempFileMode); err != nil {
		f.Close()
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to set permissions: %w", err)
	}

	if _, err := f.WriteString(content); err != nil {
		f.Close()
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to write content: %w", err)
	}

	if err := f.Close(); err != nil {
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to close file: %w", err)
	}

	return f.Name(), nil
}

// CleanupTempFile removes a temp file
func CleanupTempFile(path string, log *logrus.Logger) {
	if path == "" {
		return
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		if log != nil {
			log.WithError(err).WithField("path", path).Warn("Failed to remove temp file")
		}
	}
}

// CleanupStaleFiles removes temp files older than StaleFileThreshold
// Should be called on service startup to clean up from crashes
func CleanupStaleFiles(log *logrus.Logger) {
	entries, err := os.ReadDir(tempDir)
	if err != nil {
		// Directory doesn't exist yet
		return
	}

	now := time.Now()
	cleaned := 0

	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), TempFilePrefix) {
			continue
		}

		info, err := entry.Info()
		if err != nil {
			continue
		}

		// Remove files older than threshold (likely from crash)
		if now.Sub(info.ModTime()) > StaleFileThreshold {
			path := filepath.Join(tempDir, entry.Name())
			if err := os.Remove(path); err == nil {
				cleaned++
			}
		}
	}

	if cleaned > 0 && log != nil {
		log.WithField("count", cleaned).Info("Cleaned up stale temp files from previous run")
	}
}
