package handlers

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/sirupsen/logrus"
	"gopkg.in/yaml.v3"
)

// ScanComposeDirsRequest is the request for scanning directories for compose files
type ScanComposeDirsRequest struct {
	Paths     []string `json:"paths"`
	Recursive bool     `json:"recursive"`
	MaxDepth  int      `json:"max_depth"`
}

// ComposeFileInfo contains metadata about a discovered compose file
type ComposeFileInfo struct {
	Path        string    `json:"path"`
	ProjectName string    `json:"project_name"`
	Services    []string  `json:"services"`
	Size        int64     `json:"size"`
	Modified    time.Time `json:"modified"`
}

// ScanComposeDirsResult is the response for directory scanning
type ScanComposeDirsResult struct {
	Success      bool              `json:"success"`
	ComposeFiles []ComposeFileInfo `json:"compose_files"`
	Error        string            `json:"error,omitempty"`
}

// ScanHandler handles directory scanning for compose files
type ScanHandler struct {
	log       *logrus.Logger
	sendEvent func(eventType string, payload interface{}) error
}

// NewScanHandler creates a new scan handler
func NewScanHandler(
	log *logrus.Logger,
	sendEvent func(eventType string, payload interface{}) error,
) *ScanHandler {
	return &ScanHandler{
		log:       log,
		sendEvent: sendEvent,
	}
}

// ScanComposeDirs scans directories for docker-compose files
func (h *ScanHandler) ScanComposeDirs(ctx context.Context, req ScanComposeDirsRequest) ScanComposeDirsResult {
	h.log.WithFields(logrus.Fields{
		"paths":     req.Paths,
		"recursive": req.Recursive,
		"max_depth": req.MaxDepth,
	}).Info("Starting compose directory scan")

	// Always start with default paths, then add any user-provided paths
	allPaths := defaultScanPaths()
	if len(req.Paths) > 0 {
		// Add user paths, deduplicating
		seen := make(map[string]bool)
		for _, p := range allPaths {
			seen[p] = true
		}
		for _, p := range req.Paths {
			if !seen[p] {
				allPaths = append(allPaths, p)
				seen[p] = true
			}
		}
	}
	req.Paths = allPaths

	if req.MaxDepth <= 0 {
		req.MaxDepth = 5 // Deep enough for /var/lib/docker/volumes/<name>/_data/compose/
	}

	// Initialize as empty slice (not nil) so JSON marshals to [] not null
	composeFiles := []ComposeFileInfo{}

	for _, basePath := range req.Paths {
		// Validate path is safe to scan
		if !isPathSafe(basePath) {
			h.log.WithField("path", basePath).Warn("Skipping unsafe path")
			continue
		}

		// Check if path exists
		info, err := os.Stat(basePath)
		if err != nil {
			h.log.WithError(err).WithField("path", basePath).Debug("Path not accessible")
			continue
		}
		if !info.IsDir() {
			continue
		}

		// Scan directory
		found := h.scanDirectory(ctx, basePath, req.Recursive, req.MaxDepth, 0)
		composeFiles = append(composeFiles, found...)
	}

	h.log.WithField("count", len(composeFiles)).Info("Compose directory scan completed")

	return ScanComposeDirsResult{
		Success:      true,
		ComposeFiles: composeFiles,
	}
}

// scanDirectory recursively scans a directory for compose files
func (h *ScanHandler) scanDirectory(ctx context.Context, dir string, recursive bool, maxDepth, currentDepth int) []ComposeFileInfo {
	var results []ComposeFileInfo

	// Check context cancellation
	select {
	case <-ctx.Done():
		return results
	default:
	}

	// Check depth limit
	if currentDepth > maxDepth {
		return results
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		h.log.WithError(err).WithField("dir", dir).Debug("Cannot read directory")
		return results
	}

	for _, entry := range entries {
		// Check context cancellation
		select {
		case <-ctx.Done():
			return results
		default:
		}

		entryPath := filepath.Join(dir, entry.Name())

		if entry.IsDir() {
			// Skip hidden directories and common system directories
			if strings.HasPrefix(entry.Name(), ".") {
				continue
			}
			if shouldSkipDirectory(entry.Name()) {
				continue
			}

			// Recurse into subdirectory
			if recursive {
				subResults := h.scanDirectory(ctx, entryPath, recursive, maxDepth, currentDepth+1)
				results = append(results, subResults...)
			}
		} else {
			// Check if this is a compose file
			if isComposeFile(entry.Name()) {
				info, err := h.parseComposeFile(entryPath)
				if err != nil {
					h.log.WithError(err).WithField("path", entryPath).Debug("Failed to parse compose file")
					continue
				}
				if info != nil {
					results = append(results, *info)
				}
			}
		}
	}

	return results
}

// parseComposeFile reads and parses a compose file to extract metadata
func (h *ScanHandler) parseComposeFile(path string) (*ComposeFileInfo, error) {
	// Get file info
	fileInfo, err := os.Stat(path)
	if err != nil {
		return nil, err
	}

	// Read file
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	// Parse YAML
	var compose struct {
		Name     string                 `yaml:"name"`
		Services map[string]interface{} `yaml:"services"`
	}

	if err := yaml.Unmarshal(content, &compose); err != nil {
		return nil, err
	}

	// Must have services to be a valid compose file
	if len(compose.Services) == 0 {
		return nil, nil
	}

	// Extract service names
	var services []string
	for svc := range compose.Services {
		services = append(services, svc)
	}

	// Determine project name (from name: field or directory name)
	projectName := compose.Name
	if projectName == "" {
		projectName = filepath.Base(filepath.Dir(path))
	}

	return &ComposeFileInfo{
		Path:        path,
		ProjectName: projectName,
		Services:    services,
		Size:        fileInfo.Size(),
		Modified:    fileInfo.ModTime(),
	}, nil
}

// defaultScanPaths returns common paths where compose files are typically found
func defaultScanPaths() []string {
	paths := []string{
		"/opt",
		"/srv",
		"/var/lib/docker-compose",
		"/var/lib/docker/volumes", // Portainer and other tools store compose files in volumes
	}

	// Add home directories
	homeDir, err := os.UserHomeDir()
	if err == nil && homeDir != "" {
		paths = append(paths, homeDir)
	}

	// Check for common stacks directories
	if _, err := os.Stat("/stacks"); err == nil {
		paths = append(paths, "/stacks")
	}
	if _, err := os.Stat("/docker"); err == nil {
		paths = append(paths, "/docker")
	}

	return paths
}

// isPathSafe checks if a path is safe to scan (not a system directory)
func isPathSafe(path string) bool {
	// Normalize path
	path = filepath.Clean(path)

	// Block system directories
	blockedPrefixes := []string{
		"/proc",
		"/sys",
		"/dev",
		"/run",
		"/boot",
		"/bin",
		"/sbin",
		"/lib",
		"/lib64",
		"/usr/bin",
		"/usr/sbin",
		"/usr/lib",
		"/etc/ssl",
		"/etc/ssh",
		"/etc/shadow",
		"/etc/passwd",
	}

	for _, prefix := range blockedPrefixes {
		if path == prefix || strings.HasPrefix(path, prefix+"/") {
			return false
		}
	}

	return true
}

// shouldSkipDirectory returns true for directories that should not be scanned
func shouldSkipDirectory(name string) bool {
	skipDirs := []string{
		"node_modules",
		"vendor",
		"__pycache__",
		".git",
		".svn",
		"venv",
		".venv",
		"dist",
		"build",
		"target",
	}

	for _, skip := range skipDirs {
		if name == skip {
			return true
		}
	}
	return false
}

// isComposeFile checks if a filename is a Docker Compose file
func isComposeFile(name string) bool {
	composeNames := []string{
		"docker-compose.yml",
		"docker-compose.yaml",
		"compose.yml",
		"compose.yaml",
	}

	nameLower := strings.ToLower(name)
	for _, cn := range composeNames {
		if nameLower == cn {
			return true
		}
	}
	return false
}

// ReadComposeFileRequest is the request for reading a compose file's content
type ReadComposeFileRequest struct {
	Path string `json:"path"`
}

// ReadComposeFileResult is the response containing file content
type ReadComposeFileResult struct {
	Success    bool   `json:"success"`
	Path       string `json:"path"`
	Content    string `json:"content,omitempty"`
	EnvContent string `json:"env_content,omitempty"` // .env file if exists
	Error      string `json:"error,omitempty"`
}

// ReadComposeFile reads a compose file's content
func (h *ScanHandler) ReadComposeFile(ctx context.Context, req ReadComposeFileRequest) ReadComposeFileResult {
	h.log.WithField("path", req.Path).Info("Reading compose file")

	// Validate path is safe
	if !isPathSafe(req.Path) {
		h.log.WithField("path", req.Path).Warn("Path not allowed")
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "Path not allowed",
		}
	}

	// Validate it's a compose file
	if !isComposeFile(filepath.Base(req.Path)) {
		h.log.WithField("path", req.Path).Warn("Not a compose file")
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "Not a compose file",
		}
	}

	// Validate file exists and is a regular file
	fileInfo, err := os.Stat(req.Path)
	if err != nil {
		h.log.WithError(err).WithField("path", req.Path).Debug("File not accessible")
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "File not found or not accessible",
		}
	}
	if fileInfo.IsDir() {
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "Path is a directory, not a file",
		}
	}

	// Limit file size to 1MB to prevent memory issues
	const maxFileSize = 1024 * 1024
	if fileInfo.Size() > maxFileSize {
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "File too large (max 1MB)",
		}
	}

	// Read compose file
	content, err := os.ReadFile(req.Path)
	if err != nil {
		h.log.WithError(err).WithField("path", req.Path).Debug("Failed to read file")
		return ReadComposeFileResult{
			Success: false,
			Path:    req.Path,
			Error:   "Failed to read file",
		}
	}

	// Try to read .env file in same directory
	var envContent string
	envPath := filepath.Join(filepath.Dir(req.Path), ".env")
	if envData, err := os.ReadFile(envPath); err == nil {
		envContent = string(envData)
		h.log.WithField("env_path", envPath).Debug("Found .env file")
	}

	h.log.WithFields(logrus.Fields{
		"path":        req.Path,
		"size":        len(content),
		"has_env":     envContent != "",
	}).Info("Compose file read successfully")

	return ReadComposeFileResult{
		Success:    true,
		Path:       req.Path,
		Content:    string(content),
		EnvContent: envContent,
	}
}
