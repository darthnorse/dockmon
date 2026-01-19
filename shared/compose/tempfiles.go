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
	if err := os.MkdirAll(tempDir, TempDirMode); err != nil {
		// Log to stderr since logrus isn't initialized yet.
		// Service continues; WriteComposeFile will fail with a clearer error.
		fmt.Fprintf(os.Stderr, "CRITICAL: Failed to create compose temp directory %s: %v\n", tempDir, err)
	}
}

// GetTempDir returns the compose temp directory path
func GetTempDir() string {
	return tempDir
}

// isUnderTempDir checks if the given path is safely under our temp directory.
// Returns the cleaned path if valid, or an error describing the validation failure.
// This prevents path traversal attacks by checking the relative path.
func isUnderTempDir(path string) (string, error) {
	cleaned := filepath.Clean(path)
	cleanTempDir := filepath.Clean(tempDir)

	relPath, err := filepath.Rel(cleanTempDir, cleaned)
	if err != nil {
		return "", fmt.Errorf("failed to compute relative path: %w", err)
	}

	if strings.HasPrefix(relPath, "..") || relPath == "." {
		return "", fmt.Errorf("path escapes temp directory: %s (relative: %s)", path, relPath)
	}

	return cleaned, nil
}

// WriteComposeFile writes compose content to a secure temp file in a unique subdirectory.
// Each deployment gets its own subdirectory to prevent race conditions with .env files.
// Returns the path to the temp file. Caller is responsible for cleanup via CleanupComposeDir.
func WriteComposeFile(content string) (string, error) {
	// Ensure base temp dir exists with proper permissions
	if err := os.MkdirAll(tempDir, TempDirMode); err != nil {
		return "", fmt.Errorf("failed to create temp dir: %w", err)
	}

	// Create a unique subdirectory for this deployment
	// This isolates each deployment's .env file to prevent race conditions
	subDir, err := os.MkdirTemp(tempDir, TempFilePrefix)
	if err != nil {
		return "", fmt.Errorf("failed to create deployment temp dir: %w", err)
	}

	// Set restrictive permissions on subdirectory
	if err := os.Chmod(subDir, TempDirMode); err != nil {
		os.RemoveAll(subDir)
		return "", fmt.Errorf("failed to set dir permissions: %w", err)
	}

	// Write compose file into the subdirectory
	composePath := filepath.Join(subDir, "docker-compose.yml")
	if err := os.WriteFile(composePath, []byte(content), TempFileMode); err != nil {
		os.RemoveAll(subDir)
		return "", fmt.Errorf("failed to write compose file: %w", err)
	}

	return composePath, nil
}

// WriteEnvFile writes .env content to the same directory as the compose file.
// This allows env_file: .env references in compose files to resolve correctly.
// Returns the path to the .env file. Caller is responsible for cleanup.
func WriteEnvFile(composeFilePath, envContent string) (string, error) {
	if envContent == "" {
		return "", nil
	}

	// Defense in depth: validate the compose file path is under our temp directory
	dir, err := isUnderTempDir(filepath.Dir(composeFilePath))
	if err != nil {
		return "", fmt.Errorf("invalid compose file path: %w", err)
	}

	// Write .env in the same directory as the compose file
	envFilePath := filepath.Join(dir, ".env")

	if err := os.WriteFile(envFilePath, []byte(envContent), TempFileMode); err != nil {
		return "", fmt.Errorf("failed to write .env file: %w", err)
	}

	return envFilePath, nil
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

// CleanupComposeDir removes the deployment subdirectory containing compose and .env files.
// Pass the compose file path; this will remove its parent directory.
func CleanupComposeDir(composeFilePath string, log *logrus.Logger) {
	if composeFilePath == "" {
		return
	}

	// Validate path is under temp directory (prevents path traversal attacks)
	dir, err := isUnderTempDir(filepath.Dir(composeFilePath))
	if err != nil {
		if log != nil {
			log.WithError(err).WithField("path", composeFilePath).Warn("Refusing to remove directory outside temp area")
		}
		return
	}

	// Check for symlink attacks: verify the directory is not a symlink
	// that could redirect RemoveAll to an unintended location
	info, err := os.Lstat(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return // Already gone, nothing to do
		}
		if log != nil {
			log.WithError(err).WithField("path", dir).Warn("Failed to stat directory for cleanup")
		}
		return
	}

	// Reject symlinks - they could point outside our temp area
	if info.Mode().Type() == os.ModeSymlink {
		if log != nil {
			log.WithField("path", dir).Warn("Refusing to remove symlink in cleanup")
		}
		return
	}

	if err := os.RemoveAll(dir); err != nil && !os.IsNotExist(err) {
		if log != nil {
			log.WithError(err).WithField("path", dir).Warn("Failed to remove compose temp dir")
		}
	}
}

// TLSFiles holds paths to TLS certificate temp files
type TLSFiles struct {
	CAFile   string
	CertFile string
	KeyFile  string
}

// WriteTLSFiles writes TLS PEM content to temp files for Docker CLI usage.
// Returns paths to the temp files. Caller must call Cleanup() when done.
func WriteTLSFiles(caCert, cert, key string) (*TLSFiles, error) {
	// Ensure temp dir exists with proper permissions
	if err := os.MkdirAll(tempDir, TempDirMode); err != nil {
		return nil, fmt.Errorf("failed to create temp dir: %w", err)
	}

	files := &TLSFiles{}
	var err error

	// Write CA cert
	if caCert != "" {
		files.CAFile, err = writeTempPEM("ca-", caCert)
		if err != nil {
			return nil, fmt.Errorf("failed to write CA cert: %w", err)
		}
	}

	// Write client cert
	if cert != "" {
		files.CertFile, err = writeTempPEM("cert-", cert)
		if err != nil {
			files.Cleanup(nil)
			return nil, fmt.Errorf("failed to write client cert: %w", err)
		}
	}

	// Write client key
	if key != "" {
		files.KeyFile, err = writeTempPEM("key-", key)
		if err != nil {
			files.Cleanup(nil)
			return nil, fmt.Errorf("failed to write client key: %w", err)
		}
	}

	return files, nil
}

// writeTempPEM writes PEM content to a temp file
func writeTempPEM(prefix, content string) (string, error) {
	f, err := os.CreateTemp(tempDir, TempFilePrefix+prefix+"*.pem")
	if err != nil {
		return "", err
	}

	if err := f.Chmod(TempFileMode); err != nil {
		f.Close()
		os.Remove(f.Name())
		return "", err
	}

	if _, err := f.WriteString(content); err != nil {
		f.Close()
		os.Remove(f.Name())
		return "", err
	}

	if err := f.Close(); err != nil {
		os.Remove(f.Name())
		return "", err
	}

	return f.Name(), nil
}

// Cleanup removes all TLS temp files
func (t *TLSFiles) Cleanup(log *logrus.Logger) {
	if t == nil {
		return
	}
	CleanupTempFile(t.CAFile, log)
	CleanupTempFile(t.CertFile, log)
	CleanupTempFile(t.KeyFile, log)
}

// CleanupStaleFiles removes temp files and directories older than StaleFileThreshold
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
		name := entry.Name()

		// Clean up deployment subdirectories (compose-*) and legacy files
		if !strings.HasPrefix(name, TempFilePrefix) {
			continue
		}

		info, err := entry.Info()
		if err != nil {
			continue
		}

		// Remove entries older than threshold (likely from crash)
		if now.Sub(info.ModTime()) > StaleFileThreshold {
			path := filepath.Join(tempDir, name)
			if entry.IsDir() {
				if err := os.RemoveAll(path); err == nil {
					cleaned++
				}
			} else {
				if err := os.Remove(path); err == nil {
					cleaned++
				}
			}
		}
	}

	if cleaned > 0 && log != nil {
		log.WithField("count", cleaned).Info("Cleaned up stale temp files from previous run")
	}
}
