package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/sirupsen/logrus"
)

// SelfUpdateHandler manages agent self-updates
type SelfUpdateHandler struct {
	myContainerID string
	dataDir       string
	log           *logrus.Logger
	sendEvent     func(msgType string, payload interface{}) error
}

// NewSelfUpdateHandler creates a new self-update handler
func NewSelfUpdateHandler(myContainerID, dataDir string, log *logrus.Logger, sendEvent func(string, interface{}) error) *SelfUpdateHandler {
	return &SelfUpdateHandler{
		myContainerID: myContainerID,
		dataDir:       dataDir,
		log:           log,
		sendEvent:     sendEvent,
	}
}

// SelfUpdateRequest contains parameters for self-update
type SelfUpdateRequest struct {
	Version    string `json:"version"`
	BinaryURL  string `json:"binary_url"`
	Checksum   string `json:"checksum,omitempty"`
}

// SelfUpdateProgress represents self-update progress events
type SelfUpdateProgress struct {
	Stage   string `json:"stage"`
	Message string `json:"message"`
	Error   string `json:"error,omitempty"`
}

// UpdateLockFile represents the coordination file for updates
type UpdateLockFile struct {
	Version       string    `json:"version"`
	NewBinaryPath string    `json:"new_binary_path"`
	OldBinaryPath string    `json:"old_binary_path"`
	Timestamp     time.Time `json:"timestamp"`
}

// PerformSelfUpdate downloads new agent and prepares for update
func (h *SelfUpdateHandler) PerformSelfUpdate(ctx context.Context, req SelfUpdateRequest) error {
	if h.myContainerID == "" {
		return fmt.Errorf("self-update not available: container ID not detected")
	}

	h.log.WithFields(logrus.Fields{
		"version":    req.Version,
		"binary_url": req.BinaryURL,
	}).Info("Starting self-update")

	// Step 1: Download new binary
	h.sendProgress("download", fmt.Sprintf("Downloading version %s", req.Version))

	newBinaryPath := filepath.Join(h.dataDir, "agent-new")
	if err := h.downloadBinary(ctx, req.BinaryURL, newBinaryPath); err != nil {
		h.sendProgressError("download", err)
		return fmt.Errorf("failed to download binary: %w", err)
	}

	// Step 2: Verify checksum if provided
	if req.Checksum != "" {
		h.sendProgress("verify", "Verifying checksum")
		// TODO: Implement checksum verification
		h.log.Warn("Checksum verification not yet implemented")
	}

	// Step 3: Make binary executable
	if err := os.Chmod(newBinaryPath, 0755); err != nil {
		h.sendProgressError("chmod", err)
		return fmt.Errorf("failed to make binary executable: %w", err)
	}

	// Step 4: Write update lock file
	h.sendProgress("prepare", "Preparing update coordination")
	lockFile := UpdateLockFile{
		Version:       req.Version,
		NewBinaryPath: newBinaryPath,
		OldBinaryPath: "/app/agent",  // Current binary path in container
		Timestamp:     time.Now(),
	}

	lockFilePath := filepath.Join(h.dataDir, "update.lock")
	if err := h.writeLockFile(lockFilePath, &lockFile); err != nil {
		h.sendProgressError("prepare", err)
		return fmt.Errorf("failed to write lock file: %w", err)
	}

	h.sendProgress("complete", "Update prepared, agent will restart")

	h.log.Info("Self-update prepared successfully, agent should exit and restart")

	return nil
}

// CheckAndApplyUpdate checks for pending update on startup
func (h *SelfUpdateHandler) CheckAndApplyUpdate() error {
	lockFilePath := filepath.Join(h.dataDir, "update.lock")

	// Check if lock file exists
	if _, err := os.Stat(lockFilePath); os.IsNotExist(err) {
		// No pending update
		return nil
	}

	h.log.Info("Found pending update, applying...")

	// Read lock file
	lockFile, err := h.readLockFile(lockFilePath)
	if err != nil {
		h.log.WithError(err).Error("Failed to read lock file")
		// Remove corrupt lock file
		os.Remove(lockFilePath)
		return fmt.Errorf("failed to read lock file: %w", err)
	}

	// Check if new binary exists
	if _, err := os.Stat(lockFile.NewBinaryPath); os.IsNotExist(err) {
		h.log.Error("New binary not found, aborting update")
		os.Remove(lockFilePath)
		return fmt.Errorf("new binary not found: %s", lockFile.NewBinaryPath)
	}

	// Backup old binary
	backupPath := lockFile.OldBinaryPath + ".backup"
	if err := h.copyFile(lockFile.OldBinaryPath, backupPath); err != nil {
		h.log.WithError(err).Warn("Failed to backup old binary")
		// Continue anyway
	}

	// Replace old binary with new binary
	if err := os.Rename(lockFile.NewBinaryPath, lockFile.OldBinaryPath); err != nil {
		h.log.WithError(err).Error("Failed to replace binary")
		// Try to restore backup
		if backupErr := os.Rename(backupPath, lockFile.OldBinaryPath); backupErr != nil {
			h.log.WithError(backupErr).Fatal("Failed to restore backup, agent may be broken!")
		}
		os.Remove(lockFilePath)
		return fmt.Errorf("failed to replace binary: %w", err)
	}

	// Make new binary executable
	if err := os.Chmod(lockFile.OldBinaryPath, 0755); err != nil {
		h.log.WithError(err).Error("Failed to make new binary executable")
		// Continue anyway, it might work
	}

	// Clean up
	os.Remove(backupPath)
	os.Remove(lockFilePath)

	h.log.WithField("version", lockFile.Version).Info("Self-update applied successfully")

	return nil
}

// downloadBinary downloads a binary from URL to destination
func (h *SelfUpdateHandler) downloadBinary(ctx context.Context, url, dest string) error {
	// Create HTTP client with timeout
	client := &http.Client{
		Timeout: 5 * time.Minute,
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	// Execute request
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to download: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed with status: %d", resp.StatusCode)
	}

	// Create destination file
	out, err := os.Create(dest)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer out.Close()

	// Copy data
	_, err = io.Copy(out, resp.Body)
	if err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	return nil
}

// copyFile copies a file from src to dst
func (h *SelfUpdateHandler) copyFile(src, dst string) error {
	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, sourceFile)
	return err
}

// writeLockFile writes the update lock file
func (h *SelfUpdateHandler) writeLockFile(path string, lockFile *UpdateLockFile) error {
	data, err := json.MarshalIndent(lockFile, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal lock file: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write lock file: %w", err)
	}

	return nil
}

// readLockFile reads the update lock file
func (h *SelfUpdateHandler) readLockFile(path string) (*UpdateLockFile, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read lock file: %w", err)
	}

	var lockFile UpdateLockFile
	if err := json.Unmarshal(data, &lockFile); err != nil {
		return nil, fmt.Errorf("failed to unmarshal lock file: %w", err)
	}

	return &lockFile, nil
}

// sendProgress sends a self-update progress event
func (h *SelfUpdateHandler) sendProgress(stage, message string) {
	progress := SelfUpdateProgress{
		Stage:   stage,
		Message: message,
	}

	if err := h.sendEvent("selfupdate_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send self-update progress")
	}
}

// sendProgressError sends a self-update progress error event
func (h *SelfUpdateHandler) sendProgressError(stage string, err error) {
	progress := SelfUpdateProgress{
		Stage:   stage,
		Message: "Error occurred",
		Error:   err.Error(),
	}

	if sendErr := h.sendEvent("selfupdate_progress", progress); sendErr != nil {
		h.log.WithError(sendErr).Warn("Failed to send self-update progress error")
	}
}
