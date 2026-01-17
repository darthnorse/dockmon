package compose

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/compose-spec/compose-go/v2/cli"
	"github.com/compose-spec/compose-go/v2/types"
	dockercli "github.com/docker/cli/cli/command"
	clitypes "github.com/docker/cli/cli/config/types"
	"github.com/docker/cli/cli/flags"
	"github.com/docker/compose/v2/pkg/api"
	"github.com/docker/compose/v2/pkg/compose"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/registry"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/jsonmessage"
	"github.com/sirupsen/logrus"
)

// Service provides Docker Compose operations
type Service struct {
	dockerClient *client.Client
	log          *logrus.Logger
	progressFn   ProgressCallback
}

// NewService creates a new compose Service
// The dockerClient should be configured for the target Docker host (local or remote)
func NewService(dockerClient *client.Client, log *logrus.Logger, opts ...Option) *Service {
	s := &Service{
		dockerClient: dockerClient,
		log:          log,
	}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Deploy executes a compose deployment
func (s *Service) Deploy(ctx context.Context, req DeployRequest) *DeployResult {
	s.logInfo("Starting compose deployment", logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
	})

	s.sendProgress(ProgressEvent{
		Stage:    StageValidating,
		Progress: 5,
		Message:  "Validating deployment...",
	})

	// Write compose content to temp file
	composeFile, err := WriteComposeFile(req.ComposeYAML)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to write compose file: %v", err))
	}
	defer CleanupTempFile(composeFile, s.log)

	var result *DeployResult

	switch req.Action {
	case "up":
		result = s.runComposeUp(ctx, req, composeFile)
	case "down":
		result = s.runComposeDown(ctx, req, composeFile)
	case "restart":
		s.sendProgress(ProgressEvent{
			Stage:    StageStarting,
			Progress: 30,
			Message:  "Stopping services...",
		})
		downReq := req
		downReq.RemoveVolumes = false
		downResult := s.runComposeDown(ctx, downReq, composeFile)
		if !downResult.Success {
			return downResult
		}

		s.sendProgress(ProgressEvent{
			Stage:    StageStarting,
			Progress: 50,
			Message:  "Starting services...",
		})
		result = s.runComposeUp(ctx, req, composeFile)
	default:
		result = s.failResult(req.DeploymentID, fmt.Sprintf("Unknown action: %s", req.Action))
	}

	return result
}

// Teardown removes a compose stack
func (s *Service) Teardown(ctx context.Context, req DeployRequest) *DeployResult {
	req.Action = "down"
	return s.Deploy(ctx, req)
}

// createComposeService creates a new compose service connected to Docker.
// If registry credentials are provided, they are configured on the CLI
// so that compose can authenticate when pulling images from private registries.
func (s *Service) createComposeService(ctx context.Context, credentials []RegistryCredential) (api.Compose, *dockercli.DockerCli, error) {
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(os.Stdout),
		dockercli.WithErrorStream(os.Stderr),
	)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create Docker CLI: %w", err)
	}

	opts := flags.NewClientOptions()
	if err := cli.Initialize(opts); err != nil {
		return nil, nil, fmt.Errorf("failed to initialize Docker CLI: %w", err)
	}

	// Configure registry credentials on the CLI's in-memory config.
	// This allows compose to authenticate when pulling images from private registries.
	if len(credentials) > 0 {
		configFile := cli.ConfigFile()
		if configFile.AuthConfigs == nil {
			configFile.AuthConfigs = make(map[string]clitypes.AuthConfig)
		}

		for _, cred := range credentials {
			serverAddr := cred.RegistryURL
			// Normalize Docker Hub addresses
			if serverAddr == "" || serverAddr == "docker.io" {
				serverAddr = "https://index.docker.io/v1/"
			}

			configFile.AuthConfigs[serverAddr] = clitypes.AuthConfig{
				Username:      cred.Username,
				Password:      cred.Password,
				ServerAddress: serverAddr,
			}
			s.logDebug("Configured registry credentials", logrus.Fields{"registry": cred.RegistryURL})
		}

		// Disable external credential stores to ensure our in-memory credentials are used.
		configFile.CredentialsStore = ""

		s.logInfo("Registry credentials configured for compose", logrus.Fields{"count": len(credentials)})
	}

	composeService := compose.NewComposeService(cli)
	return composeService, cli, nil
}

// loadProject loads a compose project from file content
func (s *Service) loadProject(ctx context.Context, composeFile, projectName string, envVars map[string]string, profiles []string) (*types.Project, error) {
	workingDir := filepath.Dir(composeFile)

	// Build environment variables slice
	var envSlice []string
	for k, v := range envVars {
		envSlice = append(envSlice, fmt.Sprintf("%s=%s", k, v))
	}

	projectOpts, err := cli.NewProjectOptions(
		[]string{composeFile},
		cli.WithWorkingDirectory(workingDir),
		cli.WithName(projectName),
		cli.WithEnv(envSlice),
		cli.WithProfiles(profiles),
		cli.WithDotEnv,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create project options: %w", err)
	}

	project, err := projectOpts.LoadProject(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to load compose project: %w", err)
	}

	return project, nil
}

// runComposeUp executes compose up using the library
func (s *Service) runComposeUp(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageParsing,
		Progress: 10,
		Message:  "Parsing compose file...",
	})

	// Create compose service with registry credentials for private image pulls
	composeService, cli, err := s.createComposeService(ctx, req.RegistryCredentials)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()

	// Load project
	project, err := s.loadProject(ctx, composeFile, req.ProjectName, req.Environment, req.Profiles)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to load compose project: %v", err))
	}

	// Remove unnecessary resources (like disabled services)
	project = project.WithoutUnnecessaryResources()

	// Set required CustomLabels for compose to track containers
	for i, svc := range project.Services {
		svc.CustomLabels = map[string]string{
			api.ProjectLabel:     project.Name,
			api.ServiceLabel:     svc.Name,
			api.VersionLabel:     api.ComposeVersion,
			api.WorkingDirLabel:  project.WorkingDir,
			api.ConfigFilesLabel: strings.Join(project.ComposeFiles, ","),
			api.OneoffLabel:      "False",
		}
		project.Services[i] = svc
	}

	// Collect service and image information for detailed progress
	serviceNames := make([]string, 0, len(project.Services))
	imageNames := make([]string, 0, len(project.Services))
	for _, svc := range project.Services {
		serviceNames = append(serviceNames, svc.Name)
		if svc.Image != "" {
			imageNames = append(imageNames, svc.Image)
		}
	}

	// Report services being deployed
	s.sendProgress(ProgressEvent{
		Stage:     StageCreating,
		Progress:  25,
		Message:   fmt.Sprintf("Deploying %d service(s): %s", len(project.Services), strings.Join(serviceNames, ", ")),
		TotalSvcs: len(project.Services),
	})

	// Pull images if requested (for redeploy/update)
	if req.PullImages {
		pullMsg := fmt.Sprintf("Pulling %d image(s)...", len(imageNames))
		if len(imageNames) <= 3 {
			pullMsg = fmt.Sprintf("Pulling image(s): %s", strings.Join(imageNames, ", "))
		}
		s.sendProgress(ProgressEvent{
			Stage:    StagePullingImage,
			Progress: 30,
			Message:  pullMsg,
		})

		// Use Docker SDK directly for image pulls to get layer-level progress
		if err := s.pullImagesWithProgress(ctx, imageNames, req.RegistryCredentials); err != nil {
			s.logError("Image pull failed", err)
			return s.failResult(req.DeploymentID, fmt.Sprintf("Image pull failed: %v", err))
		}
		s.sendProgress(ProgressEvent{
			Stage:    StagePullingImage,
			Progress: 45,
			Message:  fmt.Sprintf("Successfully pulled %d image(s)", len(imageNames)),
		})
	}

	// Configure recreate behavior
	recreatePolicy := api.RecreateDiverged // Default: recreate only if config changed
	if req.ForceRecreate {
		recreatePolicy = api.RecreateForce // Force: always recreate containers
		s.logInfo("Force recreate enabled - all containers will be recreated", nil)
	}

	// Execute up
	upOpts := api.UpOptions{
		Create: api.CreateOptions{
			RemoveOrphans: true,
			Recreate:      recreatePolicy,
		},
		Start: api.StartOptions{
			Project: project,
		},
	}

	s.logInfo("Executing compose up", logrus.Fields{
		"project_name":   req.ProjectName,
		"services_count": len(project.Services),
	})

	s.sendProgress(ProgressEvent{
		Stage:    StageStarting,
		Progress: 50,
		Message:  "Building images (if needed)...",
	})

	// Build images if compose file has build: directives
	// This is a no-op if there are no build directives
	if err := composeService.Build(ctx, project, api.BuildOptions{}); err != nil {
		s.logError("Compose build failed", err)
		return s.failResult(req.DeploymentID, fmt.Sprintf("Compose build failed: %v", err))
	}

	s.sendProgress(ProgressEvent{
		Stage:     StageStarting,
		Progress:  70,
		Message:   fmt.Sprintf("Creating and starting %d container(s): %s", len(serviceNames), strings.Join(serviceNames, ", ")),
		TotalSvcs: len(serviceNames),
	})

	if err := composeService.Up(ctx, project, upOpts); err != nil {
		s.logError("Compose up failed", err)

		// Attempt cleanup on failure
		s.logWarn("Deployment failed, attempting cleanup...")
		_ = composeService.Down(ctx, req.ProjectName, api.DownOptions{RemoveOrphans: true})

		// Include service names in error for context
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to start services (%s): %v", strings.Join(serviceNames, ", "), err))
	}

	// Wait for health checks if requested
	if req.WaitForHealthy {
		s.sendProgress(ProgressEvent{
			Stage:     StageHealthCheck,
			Progress:  85,
			Message:   fmt.Sprintf("Waiting for %d service(s) to be healthy: %s", len(serviceNames), strings.Join(serviceNames, ", ")),
			TotalSvcs: len(serviceNames),
		})

		timeout := req.HealthTimeout
		if timeout <= 0 {
			timeout = 60
		}
		if err := WaitForHealthy(ctx, composeService, req.ProjectName, timeout, s.log, s.progressFn); err != nil {
			s.logError("Health check failed", err)

			// Don't just fail - discover containers and check for partial success
			// Some containers may be running even if health checks failed
			services, discoverErr := DiscoverContainers(ctx, s.dockerClient, req.ProjectName, s.log)
			if discoverErr != nil {
				s.logWarn("Failed to discover containers after health check failure")
				return s.failResult(req.DeploymentID, fmt.Sprintf("Health check failed: %v", err))
			}

			// Use AnalyzeServiceStatus to properly detect partial success
			result := AnalyzeServiceStatus(req.DeploymentID, services, s.log)

			// Override the error message to include health check failure info
			if result.PartialSuccess {
				result.Error = NewInternalError(fmt.Sprintf("Health check failed: %v. %s",
					err, result.Error.Message))
			} else if !result.Success {
				result.Error = NewInternalError(fmt.Sprintf("Health check failed: %v", err))
			}

			s.sendProgress(ProgressEvent{
				Stage:    StageFailed,
				Progress: 100,
				Message:  fmt.Sprintf("Health check failed: %v", err),
			})

			return result
		}
		s.logInfo("All services healthy", nil)
	}

	// Discover containers
	s.sendProgress(ProgressEvent{
		Stage:    StageCompleted,
		Progress: 95,
		Message:  "Discovering containers...",
	})

	services, discoverErr := DiscoverContainers(ctx, s.dockerClient, req.ProjectName, s.log)
	if discoverErr != nil {
		s.logWarn("Failed to discover containers after deployment")
		return &DeployResult{
			DeploymentID: req.DeploymentID,
			Success:      true,
			Services:     make(map[string]ServiceResult),
			Error:        NewInternalError(fmt.Sprintf("Deployment succeeded but container discovery failed: %v", discoverErr)),
		}
	}

	result := AnalyzeServiceStatus(req.DeploymentID, services, s.log)

	if result.Success {
		// Build success message with running service count
		runningCount := 0
		for _, svc := range result.Services {
			if svc.Status == "running" {
				runningCount++
			}
		}
		s.sendProgress(ProgressEvent{
			Stage:     StageCompleted,
			Progress:  100,
			Message:   fmt.Sprintf("Deployment completed: %d/%d service(s) running", runningCount, len(result.Services)),
			TotalSvcs: len(result.Services),
		})
	} else if result.PartialSuccess {
		// Report partial success with details
		failedNames := strings.Join(result.FailedServices, ", ")
		s.sendProgress(ProgressEvent{
			Stage:    StageFailed,
			Progress: 100,
			Message:  fmt.Sprintf("Partial deployment: %d service(s) failed: %s", len(result.FailedServices), failedNames),
		})
	}

	return result
}

// runComposeDown executes compose down using the library
func (s *Service) runComposeDown(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageStarting,
		Progress: 20,
		Message:  fmt.Sprintf("Stopping stack: %s", req.ProjectName),
	})

	// Create compose service
	composeService, cli, err := s.createComposeService(ctx, req.RegistryCredentials)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()

	// Execute down
	downOpts := api.DownOptions{
		RemoveOrphans: true,
		Volumes:       req.RemoveVolumes,
	}

	if req.RemoveVolumes {
		s.logWarn("Removing volumes as requested (destructive operation)")
	}

	s.logInfo("Executing compose down", logrus.Fields{"project_name": req.ProjectName})

	if err := composeService.Down(ctx, req.ProjectName, downOpts); err != nil {
		s.logError("Compose down failed", err)
		return s.failResult(req.DeploymentID, fmt.Sprintf("Compose down failed: %v", err))
	}

	s.logInfo("Compose down completed successfully", logrus.Fields{"deployment_id": req.DeploymentID})

	s.sendProgress(ProgressEvent{
		Stage:    StageCompleted,
		Progress: 100,
		Message:  "Teardown completed",
	})

	return &DeployResult{
		DeploymentID: req.DeploymentID,
		Success:      true,
		Services:     make(map[string]ServiceResult),
	}
}

// pullImagesWithProgress pulls images using the Docker SDK with progress streaming.
// This provides layer-level progress that compose's Pull() doesn't expose.
func (s *Service) pullImagesWithProgress(ctx context.Context, images []string, credentials []RegistryCredential) error {
	// Build auth map for quick lookup
	authMap := make(map[string]string)
	for _, cred := range credentials {
		// Encode auth as base64 JSON (Docker's expected format)
		authConfig := registry.AuthConfig{
			Username:      cred.Username,
			Password:      cred.Password,
			ServerAddress: cred.RegistryURL,
		}
		authJSON, err := json.Marshal(authConfig)
		if err != nil {
			s.logWarn(fmt.Sprintf("Failed to encode auth for registry %s: %v", cred.RegistryURL, err))
			continue
		}

		encoded := base64.URLEncoding.EncodeToString(authJSON)

		// Handle Docker Hub variations (empty string or docker.io)
		if cred.RegistryURL == "" || cred.RegistryURL == "docker.io" {
			authMap["docker.io"] = encoded
			authMap["index.docker.io"] = encoded
			authMap["https://index.docker.io/v1/"] = encoded
		} else {
			authMap[cred.RegistryURL] = encoded
		}
	}

	for _, imageName := range images {
		// Skip empty image names
		if imageName == "" {
			continue
		}

		// Pull single image with progress, using closure for proper defer cleanup
		if err := s.pullSingleImage(ctx, imageName, authMap); err != nil {
			return err
		}
	}

	return nil
}

// pullSingleImage pulls a single image with progress streaming.
// Separated into its own function to ensure proper defer cleanup of the reader.
func (s *Service) pullSingleImage(ctx context.Context, imageName string, authMap map[string]string) error {
	s.sendProgress(ProgressEvent{
		Stage:   StagePullingImage,
		Message: fmt.Sprintf("Pulling %s...", imageName),
	})

	// Determine auth for this image's registry
	registryAuth := ""
	// Extract registry from image name (e.g., "ghcr.io/user/image" -> "ghcr.io")
	// Images without a dot in the first path segment are Docker Hub images
	parts := strings.SplitN(imageName, "/", 2)
	if len(parts) > 1 && strings.Contains(parts[0], ".") {
		// Has explicit registry (e.g., ghcr.io, gcr.io)
		if auth, ok := authMap[parts[0]]; ok {
			registryAuth = auth
		}
	} else {
		// Docker Hub (e.g., nginx, library/nginx, myuser/myimage)
		if auth, ok := authMap["docker.io"]; ok {
			registryAuth = auth
		}
	}

	pullOpts := image.PullOptions{
		RegistryAuth: registryAuth,
	}

	reader, err := s.dockerClient.ImagePull(ctx, imageName, pullOpts)
	if err != nil {
		return fmt.Errorf("failed to pull %s: %w", imageName, err)
	}
	defer reader.Close()

	// Use bufio.Scanner with explicit buffer sizing for robustness with large JSON responses
	scanner := bufio.NewScanner(reader)
	buf := make([]byte, 64*1024)       // 64KB initial buffer
	scanner.Buffer(buf, 1024*1024)     // 1MB max buffer

	// Throttle progress broadcasts to avoid flooding the channel
	var lastBroadcast time.Time
	const throttleInterval = 250 * time.Millisecond
	const layerIDDisplayLen = 8

	for scanner.Scan() {
		// Check for context cancellation
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var msg jsonmessage.JSONMessage
		if err := json.Unmarshal(line, &msg); err != nil {
			// Non-fatal decode errors, continue
			continue
		}

		// Check for errors in the message
		if msg.Error != nil {
			return fmt.Errorf("pull error for %s: %s", imageName, msg.Error.Message)
		}

		// Determine if this is a completion event (always send immediately)
		isCompletion := msg.Status == "Pull complete" ||
			msg.Status == "Already exists" ||
			strings.HasPrefix(msg.Status, "Digest:") ||
			strings.HasPrefix(msg.Status, "Status:")

		// Throttle non-completion events
		now := time.Now()
		shouldSend := isCompletion || now.Sub(lastBroadcast) >= throttleInterval

		if !shouldSend || msg.Status == "" {
			continue
		}

		// Build progress message
		var progressMsg string
		idPrefix := msg.ID
		if len(idPrefix) > layerIDDisplayLen {
			idPrefix = idPrefix[:layerIDDisplayLen]
		}

		switch {
		case strings.HasPrefix(msg.Status, "Pulling"):
			progressMsg = fmt.Sprintf("%s: %s", imageName, msg.Status)
		case strings.Contains(msg.Status, "Downloading"):
			if msg.ID != "" {
				progressMsg = fmt.Sprintf("Downloading %s: %s", idPrefix, msg.Progress)
			}
		case strings.Contains(msg.Status, "Extracting"):
			if msg.ID != "" {
				progressMsg = fmt.Sprintf("Extracting %s: %s", idPrefix, msg.Progress)
			}
		case msg.Status == "Pull complete" || msg.Status == "Already exists":
			if msg.ID != "" {
				progressMsg = fmt.Sprintf("Layer %s: %s", idPrefix, msg.Status)
			}
		case strings.HasPrefix(msg.Status, "Digest:") || strings.HasPrefix(msg.Status, "Status:"):
			progressMsg = msg.Status
		}

		if progressMsg != "" {
			s.sendProgress(ProgressEvent{
				Stage:   StagePullingImage,
				Message: progressMsg,
			})
			lastBroadcast = now
		}
	}

	// Check for scanner errors (e.g., connection drop, read errors)
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("error reading pull stream for %s: %w", imageName, err)
	}

	s.sendProgress(ProgressEvent{
		Stage:   StagePullingImage,
		Message: fmt.Sprintf("Pulled %s", imageName),
	})

	return nil
}

// failResult creates a failure result
func (s *Service) failResult(deploymentID, errorMsg string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageFailed,
		Progress: 100,
		Message:  errorMsg,
	})

	return &DeployResult{
		DeploymentID: deploymentID,
		Success:      false,
		Error:        CategorizeError(fmt.Errorf("%s", errorMsg)),
	}
}

// sendProgress sends a progress event if callback is set
func (s *Service) sendProgress(event ProgressEvent) {
	if s.progressFn != nil {
		s.progressFn(event)
	}
}

// Logging helpers that are nil-safe
func (s *Service) logInfo(msg string, fields logrus.Fields) {
	if s.log != nil {
		if fields != nil {
			s.log.WithFields(fields).Info(msg)
		} else {
			s.log.Info(msg)
		}
	}
}

func (s *Service) logDebug(msg string, fields logrus.Fields) {
	if s.log != nil {
		if fields != nil {
			s.log.WithFields(fields).Debug(msg)
		} else {
			s.log.Debug(msg)
		}
	}
}

func (s *Service) logWarn(msg string) {
	if s.log != nil {
		s.log.Warn(msg)
	}
}

func (s *Service) logError(msg string, err error) {
	if s.log != nil {
		s.log.WithField("error", err.Error()).Error(msg)
	}
}

// TestComposeLibrary validates that the compose library is functional
func TestComposeLibrary() error {
	// Create a minimal DockerCli to verify library works
	cli, err := dockercli.NewDockerCli()
	if err != nil {
		return fmt.Errorf("failed to create Docker CLI: %w", err)
	}

	opts := flags.NewClientOptions()
	if err := cli.Initialize(opts); err != nil {
		return fmt.Errorf("failed to initialize Docker CLI: %w", err)
	}
	defer cli.Client().Close()

	return nil
}

// GetComposeCommand returns description of compose method
func GetComposeCommand() string {
	return "Docker Compose Go library (embedded)"
}

// HasComposeSupport returns true (library always available once initialized)
func HasComposeSupport() bool {
	return TestComposeLibrary() == nil
}

// GetHostType determines if request is for local or mTLS remote
func GetHostType(req DeployRequest) string {
	if req.DockerHost == "" {
		return "local"
	}
	return "mtls"
}

// GetEnvOrDefault returns an environment variable or default value
func GetEnvOrDefault(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
