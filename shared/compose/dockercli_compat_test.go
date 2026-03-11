package compose

import (
	"context"
	"testing"

	dockercli "github.com/docker/cli/cli/command"
	clitypes "github.com/docker/cli/cli/config/types"
	"github.com/docker/cli/cli/flags"
	"github.com/docker/go-connections/tlsconfig"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// These tests validate that the docker/cli APIs we depend on in
// createComposeService() haven't changed. They exercise the constructor,
// options, initialization, config, and credential APIs without needing
// a running Docker daemon. If a docker/cli upgrade breaks any of these
// signatures or behaviors, these tests will fail.

func TestDockerCLI_NewDockerCli(t *testing.T) {
	// Validates: dockercli.NewDockerCli() constructor and functional options
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(nil),
		dockercli.WithErrorStream(nil),
	)
	require.NoError(t, err)
	assert.NotNil(t, cli)
}

func TestDockerCLI_NewClientOptions(t *testing.T) {
	// Validates: flags.NewClientOptions() and its fields
	opts := flags.NewClientOptions()
	require.NotNil(t, opts)

	// These fields are used in createComposeService for remote Docker hosts
	opts.Hosts = []string{"tcp://192.168.1.100:2376"}
	opts.TLS = true
	opts.TLSVerify = true
	opts.TLSOptions = &tlsconfig.Options{
		CAFile:   "/tmp/fake-ca.pem",
		CertFile: "/tmp/fake-cert.pem",
		KeyFile:  "/tmp/fake-key.pem",
	}

	assert.Equal(t, []string{"tcp://192.168.1.100:2376"}, opts.Hosts)
	assert.True(t, opts.TLS)
	assert.True(t, opts.TLSVerify)
	assert.Equal(t, "/tmp/fake-ca.pem", opts.TLSOptions.CAFile)
}

func TestDockerCLI_Initialize(t *testing.T) {
	// Validates: cli.Initialize(opts) method signature and basic behavior.
	// With default options (local socket), Initialize succeeds even without
	// a running Docker daemon — it only configures the client, it doesn't connect.
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(nil),
		dockercli.WithErrorStream(nil),
	)
	require.NoError(t, err)

	opts := flags.NewClientOptions()
	err = cli.Initialize(opts)
	require.NoError(t, err)
}

func TestDockerCLI_ConfigFile_AuthConfigs(t *testing.T) {
	// Validates: cli.ConfigFile() returns a config with a modifiable
	// AuthConfigs map, and clitypes.AuthConfig struct fields.
	// This is the credential configuration path in createComposeService.
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(nil),
		dockercli.WithErrorStream(nil),
	)
	require.NoError(t, err)
	require.NoError(t, cli.Initialize(flags.NewClientOptions()))

	configFile := cli.ConfigFile()
	require.NotNil(t, configFile, "ConfigFile() must not return nil")

	// Initialize AuthConfigs map if nil (matches createComposeService behavior)
	if configFile.AuthConfigs == nil {
		configFile.AuthConfigs = make(map[string]clitypes.AuthConfig)
	}

	// Set credentials (same pattern as createComposeService)
	configFile.AuthConfigs["https://index.docker.io/v1/"] = clitypes.AuthConfig{
		Username:      "testuser",
		Password:      "testpass",
		ServerAddress: "https://index.docker.io/v1/",
	}
	configFile.AuthConfigs["ghcr.io"] = clitypes.AuthConfig{
		Username:      "ghuser",
		Password:      "ghtoken",
		ServerAddress: "ghcr.io",
	}

	// Verify our entries were added (may also contain entries from local Docker config)
	assert.GreaterOrEqual(t, len(configFile.AuthConfigs), 2)

	dockerHub := configFile.AuthConfigs["https://index.docker.io/v1/"]
	assert.Equal(t, "testuser", dockerHub.Username)
	assert.Equal(t, "testpass", dockerHub.Password)
	assert.Equal(t, "https://index.docker.io/v1/", dockerHub.ServerAddress)

	ghcr := configFile.AuthConfigs["ghcr.io"]
	assert.Equal(t, "ghuser", ghcr.Username)
	assert.Equal(t, "ghtoken", ghcr.Password)

	// Disable external credential stores (matches createComposeService behavior)
	configFile.CredentialsStore = ""
	assert.Empty(t, configFile.CredentialsStore)
}

func TestDockerCLI_Client(t *testing.T) {
	// Validates: cli.Client() returns a usable Docker client after Initialize.
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(nil),
		dockercli.WithErrorStream(nil),
	)
	require.NoError(t, err)
	require.NoError(t, cli.Initialize(flags.NewClientOptions()))

	dockerClient := cli.Client()
	require.NotNil(t, dockerClient, "Client() must not return nil after Initialize")

	// Verify Close() method exists (used in defer cli.Client().Close())
	err = dockerClient.Close()
	assert.NoError(t, err)
}

func TestDockerCLI_InitializeWithRemoteHost(t *testing.T) {
	// Validates: Initialize with remote host options succeeds.
	// The Docker daemon doesn't need to be reachable — Initialize only
	// configures the client endpoint, it doesn't open a connection.
	cli, err := dockercli.NewDockerCli(
		dockercli.WithOutputStream(nil),
		dockercli.WithErrorStream(nil),
	)
	require.NoError(t, err)

	opts := flags.NewClientOptions()
	opts.Hosts = []string{"tcp://10.0.0.1:2376"}

	err = cli.Initialize(opts)
	require.NoError(t, err)

	// Client should be configured for the remote host
	dockerClient := cli.Client()
	require.NotNil(t, dockerClient)
	defer dockerClient.Close()

	// DaemonHost should reflect the configured host
	assert.Contains(t, dockerClient.DaemonHost(), "10.0.0.1:2376")
}

func TestCreateComposeService_NoDockerDaemon(t *testing.T) {
	// End-to-end test of createComposeService with registry credentials.
	// Uses a Unix socket that doesn't exist, so Initialize succeeds but
	// any actual Docker API call would fail. This tests the full setup
	// path without needing a running daemon.
	svc := newTestService()

	req := DeployRequest{
		DeploymentID: "test-deploy",
		ProjectName:  "test-project",
		RegistryCredentials: []RegistryCredential{
			{
				RegistryURL: "docker.io",
				Username:    "user1",
				Password:    "pass1",
			},
			{
				RegistryURL: "ghcr.io",
				Username:    "user2",
				Password:    "pass2",
			},
		},
	}

	composeService, cli, tlsFiles, err := svc.createComposeService(context.Background(), req)
	require.NoError(t, err)
	require.NotNil(t, composeService)
	require.NotNil(t, cli)
	assert.Nil(t, tlsFiles, "TLS files should be nil for local Docker")
	defer cli.Client().Close()

	// Verify credentials were configured on the CLI's config
	configFile := cli.ConfigFile()
	require.NotNil(t, configFile)

	// Docker Hub URL should have been normalized
	dockerHubAuth, ok := configFile.AuthConfigs[dockerHubRegistry]
	assert.True(t, ok, "Docker Hub credentials should be set at canonical URL")
	assert.Equal(t, "user1", dockerHubAuth.Username)
	assert.Equal(t, "pass1", dockerHubAuth.Password)

	// GHCR credentials
	ghcrAuth, ok := configFile.AuthConfigs["ghcr.io"]
	assert.True(t, ok, "GHCR credentials should be set")
	assert.Equal(t, "user2", ghcrAuth.Username)
	assert.Equal(t, "pass2", ghcrAuth.Password)

	// Credential store should be disabled
	assert.Empty(t, configFile.CredentialsStore)
}

func TestCreateComposeService_NoCreds(t *testing.T) {
	// Verify createComposeService works without registry credentials.
	svc := newTestService()

	req := DeployRequest{
		DeploymentID: "test-deploy",
		ProjectName:  "test-project",
	}

	composeService, cli, tlsFiles, err := svc.createComposeService(context.Background(), req)
	require.NoError(t, err)
	require.NotNil(t, composeService)
	require.NotNil(t, cli)
	assert.Nil(t, tlsFiles)
	defer cli.Client().Close()
}

func TestCreateComposeService_RemoteHost(t *testing.T) {
	// Verify createComposeService configures remote Docker host correctly.
	svc := newTestService()

	req := DeployRequest{
		DeploymentID: "test-deploy",
		ProjectName:  "test-project",
		DockerHost:   "tcp://192.168.1.50:2376",
	}

	composeService, cli, tlsFiles, err := svc.createComposeService(context.Background(), req)
	require.NoError(t, err)
	require.NotNil(t, composeService)
	require.NotNil(t, cli)
	assert.Nil(t, tlsFiles, "TLS files should be nil when no certs provided")
	defer cli.Client().Close()

	// Verify remote host was configured
	assert.Contains(t, cli.Client().DaemonHost(), "192.168.1.50:2376")
}
