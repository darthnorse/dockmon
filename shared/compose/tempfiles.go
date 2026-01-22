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
	// Used for TLS certificate files and stale file cleanup
	tempDir = filepath.Join(os.TempDir(), TempDirName)
	if err := os.MkdirAll(tempDir, TempDirMode); err != nil {
		fmt.Fprintf(os.Stderr, "CRITICAL: Failed to create compose temp directory %s: %v\n", tempDir, err)
	}
}

// GetTempDir returns the compose temp directory path
func GetTempDir() string {
	return tempDir
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

// =============================================================================
// Persistent Stack Directory Functions
// =============================================================================
//
// These functions manage persistent stack directories for compose deployments.
// Unlike temp directories, stack directories persist after deployment to support
// relative bind mounts (./data) in compose files.
//
// Directory structure: $STACKS_DIR/<project_name>/docker-compose.yml

// StackDirMode is the directory permission for stack directories
const StackDirMode os.FileMode = 0755

// StackFileMode is the file permission for stack files (readable by all for bind mounts)
const StackFileMode os.FileMode = 0644

// ValidateStackName checks that a project name is safe for filesystem use.
// Returns an error if the name could cause path traversal or other issues.
func ValidateStackName(name string) error {
	if name == "" {
		return fmt.Errorf("stack name cannot be empty")
	}

	// Reject path separators
	if strings.Contains(name, "/") || strings.Contains(name, "\\") {
		return fmt.Errorf("stack name cannot contain path separators")
	}

	// Reject . and .. to prevent directory traversal
	if name == "." || name == ".." {
		return fmt.Errorf("stack name cannot be . or ..")
	}

	// Reject names starting with . (hidden files)
	if strings.HasPrefix(name, ".") {
		return fmt.Errorf("stack name cannot start with .")
	}

	// Reject null bytes
	if strings.Contains(name, "\x00") {
		return fmt.Errorf("stack name cannot contain null bytes")
	}

	return nil
}

// isUnderStacksDir checks if the given path is safely under the stacks directory.
// Returns the cleaned path if valid, or an error describing the validation failure.
func isUnderStacksDir(stacksDir, path string) (string, error) {
	cleaned := filepath.Clean(path)
	cleanStacksDir := filepath.Clean(stacksDir)

	relPath, err := filepath.Rel(cleanStacksDir, cleaned)
	if err != nil {
		return "", fmt.Errorf("failed to compute relative path: %w", err)
	}

	if strings.HasPrefix(relPath, "..") || relPath == "." {
		return "", fmt.Errorf("path escapes stacks directory: %s (relative: %s)", path, relPath)
	}

	return cleaned, nil
}

// GetStackDir returns the directory path for a stack.
// Does not create the directory.
func GetStackDir(stacksDir, projectName string) (string, error) {
	if err := ValidateStackName(projectName); err != nil {
		return "", err
	}

	stackDir := filepath.Join(stacksDir, projectName)

	// Validate the resulting path is still under stacksDir
	_, err := isUnderStacksDir(stacksDir, stackDir)
	if err != nil {
		return "", err
	}

	return stackDir, nil
}

// WriteStackComposeFile writes compose content to a persistent stack directory.
// Creates the stack directory if it doesn't exist.
// Returns the path to the compose file.
// The directory persists after deployment to support relative bind mounts.
func WriteStackComposeFile(stacksDir, projectName, content string) (string, error) {
	stackDir, err := GetStackDir(stacksDir, projectName)
	if err != nil {
		return "", fmt.Errorf("invalid stack: %w", err)
	}

	// Create stack directory if it doesn't exist
	if err := os.MkdirAll(stackDir, StackDirMode); err != nil {
		return "", fmt.Errorf("failed to create stack directory: %w", err)
	}

	// Write compose file
	composePath := filepath.Join(stackDir, "docker-compose.yml")
	if err := os.WriteFile(composePath, []byte(content), StackFileMode); err != nil {
		return "", fmt.Errorf("failed to write compose file: %w", err)
	}

	return composePath, nil
}

// WriteStackEnvFile writes .env content to a stack directory.
// The stack directory must already exist (call WriteStackComposeFile first).
// If envContent is empty, removes any existing .env file.
// Returns the path to the .env file (empty string if no .env was written).
func WriteStackEnvFile(stacksDir, projectName, envContent string) (string, error) {
	stackDir, err := GetStackDir(stacksDir, projectName)
	if err != nil {
		return "", fmt.Errorf("invalid stack: %w", err)
	}

	envPath := filepath.Join(stackDir, ".env")

	// If no env content, remove existing .env file if present
	if envContent == "" {
		if err := os.Remove(envPath); err != nil && !os.IsNotExist(err) {
			return "", fmt.Errorf("failed to remove .env file: %w", err)
		}
		return "", nil
	}

	// Write .env file
	if err := os.WriteFile(envPath, []byte(envContent), StackFileMode); err != nil {
		return "", fmt.Errorf("failed to write .env file: %w", err)
	}

	return envPath, nil
}

// DeleteStackDir removes a stack directory and all its contents.
// Used when a stack is deleted (after docker compose down).
// Safe to call if directory doesn't exist.
func DeleteStackDir(stacksDir, projectName string, log *logrus.Logger) error {
	stackDir, err := GetStackDir(stacksDir, projectName)
	if err != nil {
		return fmt.Errorf("invalid stack: %w", err)
	}

	// Validate path is under stacks directory (defense in depth)
	_, err = isUnderStacksDir(stacksDir, stackDir)
	if err != nil {
		return fmt.Errorf("refusing to delete: %w", err)
	}

	// Check for symlink attacks
	info, err := os.Lstat(stackDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // Already gone, nothing to do
		}
		return fmt.Errorf("failed to stat stack directory: %w", err)
	}

	if info.Mode().Type() == os.ModeSymlink {
		return fmt.Errorf("refusing to delete symlink: %s", stackDir)
	}

	if err := os.RemoveAll(stackDir); err != nil {
		return fmt.Errorf("failed to delete stack directory: %w", err)
	}

	if log != nil {
		log.WithField("stack", projectName).Info("Deleted stack directory")
	}

	return nil
}
