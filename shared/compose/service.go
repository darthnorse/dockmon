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
	"sync"
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
	"github.com/docker/go-connections/tlsconfig"
	"github.com/sirupsen/logrus"
)

const (
	// dockerHubRegistry is the canonical Docker Hub registry address
	dockerHubRegistry = "https://index.docker.io/v1/"
	// layerIDDisplayLen is the number of characters to show for layer IDs
	layerIDDisplayLen = 8
	// progressThrottleInterval limits how often progress updates are sent
	progressThrottleInterval = 250 * time.Millisecond
	// defaultHealthTimeout is the default timeout in seconds for health checks
	defaultHealthTimeout = 60
	// defaultStacksDir is the default directory for persistent stack files
	// Used when StacksDir is not specified in the request
	defaultStacksDir = "/app/data/stacks"
)

// hostStacksDiscovery lazily resolves the container-internal stacks directory
// to its host-side source path via /proc/self/mountinfo. Done once per process
// since the mount layout does not change under us at runtime.
//
// The cached value is keyed implicitly to the first caller's stacksDir.
// This is safe today because StacksDir is process-global (defaultStacksDir);
// if it ever becomes per-request, this cache must be re-keyed by stacksDir.
//
// On read error the cache stores "" and never retries — mountinfo I/O failures
// are pathological, not transient, and a permanent fallback to the explicit
// HOST_STACKS_DIR env var is the desired behavior.
var hostStacksDiscovery struct {
	once sync.Once
	path string
}

// resolveHostStacksDir returns the host-side stacks directory for the given
// DeployRequest, applying the fallback order: explicit request value,
// auto-discovery (local engines only), empty. Callers still gate on
// DockerHost == "" before using this for path rewrites, because host paths
// are meaningless for mTLS remote hosts.
func resolveHostStacksDir(req DeployRequest, stacksDir string, log *logrus.Logger) string {
	if req.HostStacksDir != "" {
		return req.HostStacksDir
	}
	if req.DockerHost != "" {
		return ""
	}
	hostStacksDiscovery.once.Do(func() {
		host, err := DiscoverHostPath(stacksDir)
		if err != nil && log != nil {
			log.WithError(err).WithField("stacks_dir", stacksDir).
				Warn("Failed to auto-discover host stacks path; falling back to request value")
		}
		// If discovery returns the input unchanged, we're either running
		// on the host or on a non-Linux kernel — no rewrite needed. Store
		// "" so the deploy flow treats it the same as no configuration.
		if host == stacksDir {
			hostStacksDiscovery.path = ""
			return
		}
		hostStacksDiscovery.path = host
		// Logged inside Once.Do so it fires exactly once per process — not a
		// bug, just less noise across many deploys.
		if log != nil {
			log.WithFields(logrus.Fields{
				"container_stacks_dir": stacksDir,
				"host_stacks_dir":      host,
			}).Info("Auto-discovered host stacks directory from /proc/self/mountinfo")
		}
	})
	return hostStacksDiscovery.path
}

// isDockerHub returns true if the registry URL refers to Docker Hub
func isDockerHub(registryURL string) bool {
	return registryURL == "" || registryURL == "docker.io" || registryURL == "index.docker.io"
}

// healthTimeoutOrDefault returns the timeout if positive, otherwise the default
func healthTimeoutOrDefault(timeout int) int {
	if timeout <= 0 {
		return defaultHealthTimeout
	}
	return timeout
}

// collectServiceInfo extracts service names and image names from a compose project
func collectServiceInfo(project *types.Project) (serviceNames, imageNames []string) {
	serviceNames = make([]string, 0, len(project.Services))
	imageNames = make([]string, 0, len(project.Services))
	for _, svc := range project.Services {
		serviceNames = append(serviceNames, svc.Name)
		if svc.Image != "" {
			imageNames = append(imageNames, svc.Image)
		}
	}
	return serviceNames, imageNames
}

// countHealthyServices returns the number of healthy services in the result
func countHealthyServices(services map[string]ServiceResult) int {
	count := 0
	for _, svc := range services {
		if IsServiceResultHealthy(svc) {
			count++
		}
	}
	return count
}

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
func (s *Service) Deploy(ctx context.Context, req DeployRequest) (result *DeployResult) {
	// Ensure Action is set on every return path
	defer func() {
		if result != nil {
			result.Action = req.Action
		}
	}()

	// Default to standard stacks directory if not specified
	stacksDir := req.StacksDir
	if stacksDir == "" {
		stacksDir = defaultStacksDir
	}

	s.logInfo("Starting compose deployment", logrus.Fields{
		"deployment_id":  req.DeploymentID,
		"project_name":   req.ProjectName,
		"action":         req.Action,
		"stacks_dir":     stacksDir,
		"host_stacks_dir": req.HostStacksDir,
	})

	s.sendProgress(ProgressEvent{
		Stage:    StageValidating,
		Progress: 5,
		Message:  "Validating deployment...",
	})

	// Write compose file to persistent stack directory
	// This allows relative bind mounts (./data) to persist across redeployments
	composeFile, err := WriteStackComposeFile(stacksDir, req.ProjectName, req.ComposeYAML)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to write compose file: %v", err))
	}

	// Write or remove .env file based on content
	// WriteStackEnvFile removes existing .env when called with empty content
	if _, err := WriteStackEnvFile(stacksDir, req.ProjectName, req.EnvFileContent); err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to write .env file: %v", err))
	}

	s.logInfo("Using persistent stack directory", logrus.Fields{
		"stack_dir": filepath.Dir(composeFile),
	})

	// For "down" action, optionally delete the stack directory
	if req.Action == "down" && req.RemoveVolumes {
		defer func() {
			if err := DeleteStackDir(stacksDir, req.ProjectName, s.log); err != nil {
				s.logWarn("Failed to delete stack directory", logrus.Fields{
					"error": err.Error(),
					"stack": req.ProjectName,
				})
			}
		}()
	}

	switch req.Action {
	case "up":
		return s.runComposeUp(ctx, req, composeFile)
	case "down":
		return s.runComposeDown(ctx, req, composeFile)
	case "restart":
		return s.runRestart(ctx, req, composeFile)
	default:
		return s.failResult(req.DeploymentID, fmt.Sprintf("Unknown action: %s", req.Action))
	}
}

// runRestart performs a compose restart by stopping then starting services
func (s *Service) runRestart(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
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
	return s.runComposeUp(ctx, req, composeFile)
}

// Teardown removes a compose stack
func (s *Service) Teardown(ctx context.Context, req DeployRequest) *DeployResult {
	req.Action = "down"
	return s.Deploy(ctx, req)
}

// createComposeService creates a new compose service connected to Docker.
// If registry credentials are provided, they are configured on the CLI
// so that compose can authenticate when pulling images from private registries.
// For remote Docker hosts, TLS certs are written to temp files (cleaned up by caller).
func (s *Service) createComposeService(ctx context.Context, req DeployRequest) (api.Compose, *dockercli.DockerCli, *TLSFiles, error) {
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(os.Stdout),
		dockercli.WithErrorStream(os.Stderr),
	)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("failed to create Docker CLI: %w", err)
	}

	opts := flags.NewClientOptions()

	// Configure remote Docker host if specified
	var tlsFiles *TLSFiles
	if req.DockerHost != "" {
		opts.Hosts = []string{req.DockerHost}

		// Configure TLS if certificates provided
		if req.TLSCACert != "" || req.TLSCert != "" || req.TLSKey != "" {
			tlsFiles, err = WriteTLSFiles(req.TLSCACert, req.TLSCert, req.TLSKey)
			if err != nil {
				return nil, nil, nil, fmt.Errorf("failed to write TLS files: %w", err)
			}

			opts.TLS = true
			opts.TLSVerify = true
			opts.TLSOptions = &tlsconfig.Options{
				CAFile:   tlsFiles.CAFile,
				CertFile: tlsFiles.CertFile,
				KeyFile:  tlsFiles.KeyFile,
			}
		}

		s.logInfo("Configuring remote Docker host", logrus.Fields{"host": req.DockerHost})
	}

	if err := cli.Initialize(opts); err != nil {
		if tlsFiles != nil {
			tlsFiles.Cleanup(s.log)
		}
		return nil, nil, nil, fmt.Errorf("failed to initialize Docker CLI: %w", err)
	}

	// Configure registry credentials on the CLI's in-memory config.
	// This allows compose to authenticate when pulling images from private registries.
	if len(req.RegistryCredentials) > 0 {
		configFile := cli.ConfigFile()
		if configFile.AuthConfigs == nil {
			configFile.AuthConfigs = make(map[string]clitypes.AuthConfig)
		}

		for _, cred := range req.RegistryCredentials {
			serverAddr := cred.RegistryURL
			if isDockerHub(serverAddr) {
				serverAddr = dockerHubRegistry
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

		s.logInfo("Registry credentials configured for compose", logrus.Fields{"count": len(req.RegistryCredentials)})
	}

	composeService := compose.NewComposeService(cli)
	return composeService, cli, tlsFiles, nil
}

// loadProject loads a compose project from file content.
// Environment variables are loaded from .env file in the working directory
// (written by WriteEnvFile before this is called).
//
// When hostWorkingDir is set (containerized deployments with HOST_STACKS_DIR),
// the project is loaded using the container-internal working directory so that
// env_file paths resolve correctly inside the container. Bind mount sources are
// then rewritten to host paths in a post-processing step.
func (s *Service) loadProject(ctx context.Context, composeFile, projectName string, profiles []string, hostWorkingDir string) (*types.Project, error) {
	workingDir := filepath.Dir(composeFile)
	envFile := filepath.Join(workingDir, ".env")

	opts := []cli.ProjectOptionsFn{
		cli.WithWorkingDirectory(workingDir),
		cli.WithName(projectName),
		cli.WithProfiles(profiles),
	}

	// Load .env file manually and pass via WithEnv for reliable interpolation
	// This bypasses compose-go's WithDotEnv which can have issues with file loading
	if _, err := os.Stat(envFile); err == nil {
		s.logInfo("Loading .env file for compose", logrus.Fields{"path": envFile})

		envVars, loadErr := loadEnvFile(envFile)
		if loadErr != nil {
			s.logWarn("Failed to parse .env file", logrus.Fields{"error": loadErr.Error()})
		} else {
			s.logInfo("Loaded env vars from .env", logrus.Fields{"count": len(envVars)})
			if len(envVars) > 0 {
				opts = append(opts, cli.WithEnv(envVars))
			}
		}
	} else {
		s.logDebug("No .env file found", logrus.Fields{"path": envFile})
	}

	projectOpts, err := cli.NewProjectOptions(
		[]string{composeFile},
		opts...,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create project options: %w", err)
	}

	project, err := projectOpts.LoadProject(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to load compose project: %w", err)
	}

	if hostWorkingDir != "" {
		s.rewriteBindMountPaths(project, workingDir, hostWorkingDir)
		// Set host path so applyComposeLabels writes the correct WorkingDirLabel
		project.WorkingDir = hostWorkingDir
	}

	return project, nil
}

// firstStrayBindSource returns the source of the first bind mount that would
// resolve to the wrong host path: non-absolute (compose-go failed to resolve)
// or still under containerStacksDir (rewrite missed it). Returns "" when safe.
func firstStrayBindSource(project *types.Project, containerStacksDir string) string {
	prefix := containerStacksDir + "/"
	for _, svc := range project.Services {
		for _, vol := range svc.Volumes {
			if vol.Type != types.VolumeTypeBind {
				continue
			}
			if !filepath.IsAbs(vol.Source) {
				return vol.Source
			}
			if vol.Source == containerStacksDir || strings.HasPrefix(vol.Source, prefix) {
				return vol.Source
			}
		}
	}
	return ""
}

// rewriteBindMountPaths rewrites bind mount source paths from container-internal
// paths to host filesystem paths. compose-go resolves relative paths against the
// container-internal working directory, but the Docker daemon needs host paths
// for bind mounts. Non-matching absolute paths and non-bind volumes are unchanged.
func (s *Service) rewriteBindMountPaths(project *types.Project, containerWorkingDir, hostWorkingDir string) {
	// Match against the parent (stacks) directory to handle both ./data and ../sibling paths.
	containerStacksDir := filepath.Dir(containerWorkingDir)
	hostStacksDir := filepath.Dir(hostWorkingDir)

	containerPrefix := containerStacksDir + "/"
	rewritten := 0
	for name, svc := range project.Services {
		modified := false
		for j, vol := range svc.Volumes {
			if vol.Type != types.VolumeTypeBind {
				continue
			}
			if strings.HasPrefix(vol.Source, containerPrefix) {
				relPath := vol.Source[len(containerStacksDir):]
				svc.Volumes[j].Source = hostStacksDir + relPath
				modified = true
				rewritten++
			}
		}
		if modified {
			project.Services[name] = svc
		}
	}

	if rewritten > 0 {
		s.logInfo("Rewrote bind mount paths for host filesystem", logrus.Fields{
			"count":                rewritten,
			"container_stacks_dir": containerStacksDir,
			"host_stacks_dir":     hostStacksDir,
		})
	}
}

// loadEnvFile reads a .env file and returns KEY=VALUE strings for compose interpolation
func loadEnvFile(path string) ([]string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var envVars []string
	scanner := bufio.NewScanner(strings.NewReader(string(content)))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		// Skip empty lines and comments
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Must have KEY=VALUE format
		idx := strings.Index(line, "=")
		if idx <= 0 {
			continue
		}

		// Add the full KEY=VALUE string
		envVars = append(envVars, line)
	}

	return envVars, scanner.Err()
}

// applyComposeLabels sets the required CustomLabels for compose to track containers
func (s *Service) applyComposeLabels(project *types.Project) {
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
}

// pullProjectImages pulls images with progress reporting
func (s *Service) pullProjectImages(ctx context.Context, imageNames []string, credentials []RegistryCredential) error {
	pullMsg := fmt.Sprintf("Pulling %d image(s)...", len(imageNames))
	if len(imageNames) <= 3 {
		pullMsg = fmt.Sprintf("Pulling image(s): %s", strings.Join(imageNames, ", "))
	}
	s.sendProgress(ProgressEvent{
		Stage:    StagePullingImage,
		Progress: 30,
		Message:  pullMsg,
	})

	if err := s.pullImagesWithProgress(ctx, imageNames, credentials); err != nil {
		s.logError("Image pull failed", err, nil)
		return err
	}

	s.sendProgress(ProgressEvent{
		Stage:    StagePullingImage,
		Progress: 45,
		Message:  fmt.Sprintf("Successfully pulled %d image(s)", len(imageNames)),
	})
	return nil
}

// waitForHealthyServices waits for health checks and returns a result if there's a failure
func (s *Service) waitForHealthyServices(ctx context.Context, composeService api.Compose, req DeployRequest, serviceNames []string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:     StageHealthCheck,
		Progress:  85,
		Message:   fmt.Sprintf("Waiting for %d service(s) to be healthy: %s", len(serviceNames), strings.Join(serviceNames, ", ")),
		TotalSvcs: len(serviceNames),
	})

	timeout := healthTimeoutOrDefault(req.HealthTimeout)
	err := WaitForHealthy(ctx, composeService, req.ProjectName, timeout, s.log, s.progressFn)
	if err == nil {
		s.logInfo("All services healthy", nil)
		return nil
	}

	s.logError("Health check failed", err, nil)

	services, discoverErr := DiscoverContainers(ctx, s.dockerClient, req.ProjectName, s.log)
	if discoverErr != nil {
		s.logWarn("Failed to discover containers after health check failure", nil)
		return s.failResult(req.DeploymentID, fmt.Sprintf("Health check failed: %v", err))
	}

	result := AnalyzeServiceStatus(req.DeploymentID, services, s.log)

	if result.PartialSuccess {
		result.Error = NewInternalError(fmt.Sprintf("Health check failed: %v. %s", err, result.Error.Message))
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

func (s *Service) runComposeUp(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageParsing,
		Progress: 10,
		Message:  "Parsing compose file...",
	})

	composeService, cli, tlsFiles, err := s.createComposeService(ctx, req)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()
	defer tlsFiles.Cleanup(s.log)

	// Compute host-side working directory for bind mount resolution.
	// Only applies for local Docker engines — for mTLS remote hosts the
	// engine is on a different machine, so host paths are meaningless.
	// The effective host stacks dir comes from the request if set, otherwise
	// we auto-discover it by reading /proc/self/mountinfo.
	stacksDir := req.StacksDir
	if stacksDir == "" {
		stacksDir = defaultStacksDir
	}
	// Normalize so trailing-slash inputs don't break prefix matching in
	// firstStrayBindSource (it builds containerStacksDir + "/" as a prefix).
	stacksDir = filepath.Clean(stacksDir)
	effectiveHostStacksDir := resolveHostStacksDir(req, stacksDir, s.log)

	var hostWorkingDir string
	if effectiveHostStacksDir != "" && req.DockerHost == "" {
		hostWorkingDir = filepath.Join(effectiveHostStacksDir, req.ProjectName)
		s.logInfo("Using host-side working directory for bind mount resolution", logrus.Fields{
			"host_working_dir":      hostWorkingDir,
			"container_working_dir": filepath.Dir(composeFile),
		})
	}

	project, err := s.loadProject(ctx, composeFile, req.ProjectName, req.Profiles, hostWorkingDir)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to load compose project: %v", err))
	}

	// Defensive check: if we attempted a rewrite but a bind source is still
	// rooted at the container-internal stacks dir, the Docker daemon will
	// silently mount from the wrong host path (Issue #211). Fail fast with
	// an actionable message rather than producing an empty-looking volume.
	if req.DockerHost == "" && effectiveHostStacksDir != "" {
		if stray := firstStrayBindSource(project, stacksDir); stray != "" {
			return s.failResult(req.DeploymentID, fmt.Sprintf(
				"Bind mount source %q is a container-internal path. "+
					"Auto-discovery of the host stacks directory failed for this deployment. "+
					"Set HOST_STACKS_DIR to the host path that maps to your %s volume and redeploy.",
				stray, filepath.Dir(stacksDir)))
		}
	}

	project = project.WithoutUnnecessaryResources()
	s.applyComposeLabels(project)
	serviceNames, imageNames := collectServiceInfo(project)

	s.sendProgress(ProgressEvent{
		Stage:     StageCreating,
		Progress:  25,
		Message:   fmt.Sprintf("Deploying %d service(s): %s", len(project.Services), strings.Join(serviceNames, ", ")),
		TotalSvcs: len(project.Services),
	})

	if req.PullImages {
		if err := s.pullProjectImages(ctx, imageNames, req.RegistryCredentials); err != nil {
			return s.failResult(req.DeploymentID, fmt.Sprintf("Image pull failed: %v", err))
		}
	}

	recreatePolicy := api.RecreateDiverged
	if req.ForceRecreate {
		recreatePolicy = api.RecreateForce
		s.logInfo("Force recreate enabled", nil)
	}

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

	if err := composeService.Build(ctx, project, api.BuildOptions{}); err != nil {
		s.logError("Compose build failed", err, nil)
		return s.failResult(req.DeploymentID, fmt.Sprintf("Compose build failed: %v", err))
	}

	s.sendProgress(ProgressEvent{
		Stage:     StageStarting,
		Progress:  70,
		Message:   fmt.Sprintf("Creating and starting %d container(s): %s", len(serviceNames), strings.Join(serviceNames, ", ")),
		TotalSvcs: len(serviceNames),
	})

	if err := composeService.Up(ctx, project, upOpts); err != nil {
		s.logError("Compose up failed", err, nil)
		s.logWarn("Deployment failed, attempting cleanup...", nil)
		_ = composeService.Down(ctx, req.ProjectName, api.DownOptions{RemoveOrphans: true})
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to start services (%s): %v", strings.Join(serviceNames, ", "), err))
	}

	if req.WaitForHealthy {
		if result := s.waitForHealthyServices(ctx, composeService, req, serviceNames); result != nil {
			return result
		}
	}

	s.sendProgress(ProgressEvent{
		Stage:    StageCompleted,
		Progress: 95,
		Message:  "Discovering containers...",
	})

	services, discoverErr := DiscoverContainers(ctx, s.dockerClient, req.ProjectName, s.log)
	if discoverErr != nil {
		s.logWarn("Failed to discover containers after deployment", nil)
		return &DeployResult{
			DeploymentID: req.DeploymentID,
			Success:      true,
			Services:     make(map[string]ServiceResult),
			Error:        NewInternalError(fmt.Sprintf("Deployment succeeded but container discovery failed: %v", discoverErr)),
		}
	}

	result := AnalyzeServiceStatus(req.DeploymentID, services, s.log)

	if result.Success {
		runningCount := countHealthyServices(result.Services)
		s.sendProgress(ProgressEvent{
			Stage:     StageCompleted,
			Progress:  100,
			Message:   fmt.Sprintf("Deployment completed: %d/%d service(s) running", runningCount, len(result.Services)),
			TotalSvcs: len(result.Services),
		})
	} else if result.PartialSuccess {
		s.sendProgress(ProgressEvent{
			Stage:    StageFailed,
			Progress: 100,
			Message:  fmt.Sprintf("Partial deployment: %d service(s) failed: %s", len(result.FailedServices), strings.Join(result.FailedServices, ", ")),
		})
	}

	return result
}

func (s *Service) runComposeDown(ctx context.Context, req DeployRequest, composeFile string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageStarting,
		Progress: 20,
		Message:  fmt.Sprintf("Stopping stack: %s", req.ProjectName),
	})

	composeService, cli, tlsFiles, err := s.createComposeService(ctx, req)
	if err != nil {
		return s.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()
	defer tlsFiles.Cleanup(s.log)

	if req.RemoveVolumes {
		s.logWarn("Removing volumes as requested (destructive operation)", nil)
	}

	s.logInfo("Executing compose down", logrus.Fields{"project_name": req.ProjectName})

	downOpts := api.DownOptions{
		RemoveOrphans: true,
		Volumes:       req.RemoveVolumes,
	}
	if err := composeService.Down(ctx, req.ProjectName, downOpts); err != nil {
		s.logError("Compose down failed", err, nil)
		return s.failResult(req.DeploymentID, fmt.Sprintf("Compose down failed: %v", err))
	}

	s.logInfo("Compose down completed", logrus.Fields{"deployment_id": req.DeploymentID})
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

// buildRegistryAuthMap creates a map of registry URLs to base64-encoded auth credentials.
// Docker Hub is mapped to multiple keys to handle its various URL formats.
func (s *Service) buildRegistryAuthMap(credentials []RegistryCredential) map[string]string {
	authMap := make(map[string]string)
	for _, cred := range credentials {
		authConfig := registry.AuthConfig{
			Username:      cred.Username,
			Password:      cred.Password,
			ServerAddress: cred.RegistryURL,
		}
		authJSON, err := json.Marshal(authConfig)
		if err != nil {
			s.logWarn("Failed to encode auth for registry", logrus.Fields{
				"registry": cred.RegistryURL,
				"error":    err.Error(),
			})
			continue
		}
		encoded := base64.URLEncoding.EncodeToString(authJSON)

		if isDockerHub(cred.RegistryURL) {
			authMap["docker.io"] = encoded
			authMap["index.docker.io"] = encoded
			authMap[dockerHubRegistry] = encoded
		} else {
			authMap[cred.RegistryURL] = encoded
		}
	}
	return authMap
}

// getRegistryFromImage extracts the registry hostname from an image reference.
// Returns "docker.io" for Docker Hub images (those without a dot in the first path segment).
func getRegistryFromImage(imageName string) string {
	parts := strings.SplitN(imageName, "/", 2)
	if len(parts) > 1 && strings.Contains(parts[0], ".") {
		return parts[0]
	}
	return "docker.io"
}

// pullImagesWithProgress pulls images using the Docker SDK with progress streaming.
func (s *Service) pullImagesWithProgress(ctx context.Context, images []string, credentials []RegistryCredential) error {
	authMap := s.buildRegistryAuthMap(credentials)

	for _, imageName := range images {
		if imageName == "" {
			continue
		}
		if err := s.pullSingleImage(ctx, imageName, authMap); err != nil {
			return err
		}
	}
	return nil
}

// pullSingleImage pulls a single image with progress streaming.
func (s *Service) pullSingleImage(ctx context.Context, imageName string, authMap map[string]string) error {
	s.sendProgress(ProgressEvent{
		Stage:   StagePullingImage,
		Message: fmt.Sprintf("Pulling %s...", imageName),
	})

	registryAuth := authMap[getRegistryFromImage(imageName)]
	pullOpts := image.PullOptions{RegistryAuth: registryAuth}

	reader, err := s.dockerClient.ImagePull(ctx, imageName, pullOpts)
	if err != nil {
		return fmt.Errorf("failed to pull %s: %w", imageName, err)
	}
	defer reader.Close()

	if err := s.streamPullProgress(ctx, reader, imageName); err != nil {
		return err
	}

	s.sendProgress(ProgressEvent{
		Stage:   StagePullingImage,
		Message: fmt.Sprintf("Pulled %s", imageName),
	})
	return nil
}

// streamPullProgress reads the image pull stream and sends progress updates.
func (s *Service) streamPullProgress(ctx context.Context, reader interface{ Read([]byte) (int, error) }, imageName string) error {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)

	var lastBroadcast time.Time

	for scanner.Scan() {
		if err := ctx.Err(); err != nil {
			return err
		}

		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var msg jsonmessage.JSONMessage
		if err := json.Unmarshal(line, &msg); err != nil {
			continue
		}

		if msg.Error != nil {
			return fmt.Errorf("pull error for %s: %s", imageName, msg.Error.Message)
		}

		progressMsg, isCompletion := s.formatPullProgressMessage(msg, imageName)
		if progressMsg == "" {
			continue
		}

		if shouldBroadcast(isCompletion, &lastBroadcast) {
			s.sendProgress(ProgressEvent{
				Stage:   StagePullingImage,
				Message: progressMsg,
			})
		}
	}

	return scanner.Err()
}

// shouldBroadcast determines if a progress update should be sent based on throttling.
// Completion events always broadcast; otherwise throttle to progressThrottleInterval.
func shouldBroadcast(isCompletion bool, lastBroadcast *time.Time) bool {
	now := time.Now()
	if isCompletion || now.Sub(*lastBroadcast) >= progressThrottleInterval {
		*lastBroadcast = now
		return true
	}
	return false
}

// formatPullProgressMessage formats a pull progress message and indicates if it's a completion event.
func (s *Service) formatPullProgressMessage(msg jsonmessage.JSONMessage, imageName string) (string, bool) {
	if msg.Status == "" {
		return "", false
	}

	idPrefix := truncateID(msg.ID)
	status := msg.Status

	// Completion events that should always be broadcast
	switch {
	case status == "Pull complete", status == "Already exists":
		if msg.ID != "" {
			return fmt.Sprintf("Layer %s: %s", idPrefix, status), true
		}
		return "", false
	case strings.HasPrefix(status, "Digest:"), strings.HasPrefix(status, "Status:"):
		return status, true
	}

	// Progress events (throttled)
	switch {
	case strings.HasPrefix(status, "Pulling"):
		return fmt.Sprintf("%s: %s", imageName, status), false
	case strings.Contains(status, "Downloading") && msg.ID != "":
		return fmt.Sprintf("Downloading %s: %s", idPrefix, msg.Progress), false
	case strings.Contains(status, "Extracting") && msg.ID != "":
		return fmt.Sprintf("Extracting %s: %s", idPrefix, msg.Progress), false
	default:
		return "", false
	}
}

// truncateID returns a truncated ID for display
func truncateID(id string) string {
	if len(id) > layerIDDisplayLen {
		return id[:layerIDDisplayLen]
	}
	return id
}

func (s *Service) failResult(deploymentID, errorMsg string) *DeployResult {
	s.sendProgress(ProgressEvent{
		Stage:    StageFailed,
		Progress: 100,
		Message:  errorMsg,
	})
	return &DeployResult{
		DeploymentID: deploymentID,
		Success:      false,
		Error:        NewInternalError(errorMsg),
	}
}

func (s *Service) sendProgress(event ProgressEvent) {
	if s.progressFn != nil {
		s.progressFn(event)
	}
}

// logWithFields is a nil-safe helper for structured logging
func (s *Service) logWithFields(level logrus.Level, msg string, fields logrus.Fields) {
	if s.log == nil {
		return
	}
	if fields == nil {
		fields = logrus.Fields{}
	}
	s.log.WithFields(fields).Log(level, msg)
}

func (s *Service) logInfo(msg string, fields logrus.Fields) {
	s.logWithFields(logrus.InfoLevel, msg, fields)
}

func (s *Service) logDebug(msg string, fields logrus.Fields) {
	s.logWithFields(logrus.DebugLevel, msg, fields)
}

func (s *Service) logWarn(msg string, fields logrus.Fields) {
	s.logWithFields(logrus.WarnLevel, msg, fields)
}

func (s *Service) logError(msg string, err error, fields logrus.Fields) {
	if fields == nil {
		fields = logrus.Fields{}
	}
	fields["error"] = err.Error()
	s.logWithFields(logrus.ErrorLevel, msg, fields)
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
