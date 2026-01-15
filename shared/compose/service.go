package compose

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/compose-spec/compose-go/v2/cli"
	"github.com/compose-spec/compose-go/v2/types"
	dockercli "github.com/docker/cli/cli/command"
	clitypes "github.com/docker/cli/cli/config/types"
	"github.com/docker/cli/cli/flags"
	"github.com/docker/compose/v2/pkg/api"
	"github.com/docker/compose/v2/pkg/compose"
	"github.com/docker/docker/client"
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
	cli, err := dockercli.NewDockerCli()
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

	s.sendProgress(ProgressEvent{
		Stage:     StageCreating,
		Progress:  25,
		Message:   fmt.Sprintf("Creating %d service(s)...", len(project.Services)),
		TotalSvcs: len(project.Services),
	})

	// Pull images if requested (for redeploy/update)
	if req.PullImages {
		s.sendProgress(ProgressEvent{
			Stage:    StagePullingImage,
			Progress: 30,
			Message:  "Pulling images...",
		})

		pullOpts := api.PullOptions{
			IgnoreFailures: false,
		}
		if err := composeService.Pull(ctx, project, pullOpts); err != nil {
			s.logError("Image pull failed", err)
			return s.failResult(req.DeploymentID, fmt.Sprintf("Image pull failed: %v", err))
		}
		s.logInfo("Images pulled successfully", nil)
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
		Stage:    StageStarting,
		Progress: 70,
		Message:  "Starting services...",
	})

	if err := composeService.Up(ctx, project, upOpts); err != nil {
		s.logError("Compose up failed", err)

		// Attempt cleanup on failure
		s.logWarn("Deployment failed, attempting cleanup...")
		_ = composeService.Down(ctx, req.ProjectName, api.DownOptions{RemoveOrphans: true})

		return s.failResult(req.DeploymentID, fmt.Sprintf("Compose up failed: %v", err))
	}

	// Wait for health checks if requested
	if req.WaitForHealthy {
		s.sendProgress(ProgressEvent{
			Stage:    StageHealthCheck,
			Progress: 85,
			Message:  "Waiting for services to be healthy...",
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
		s.sendProgress(ProgressEvent{
			Stage:    StageCompleted,
			Progress: 100,
			Message:  "Deployment completed successfully",
		})
	}

	return result
}

// runComposeDown executes compose down using the library
func (s *Service) runComposeDown(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageStarting,
		Progress: 20,
		Message:  "Running compose down...",
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
