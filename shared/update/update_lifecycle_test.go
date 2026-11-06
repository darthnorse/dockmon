//go:build integration

package update

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/sirupsen/logrus"
)

const (
	lifecycleOldImage = "alpine:3.18"
	lifecycleNewImage = "alpine:3.19"
)

type lifecycleEnv struct {
	t      *testing.T
	cli    *client.Client
	ctx    context.Context
	log    *logrus.Logger
	prefix string
}

func newLifecycleEnv(t *testing.T) *lifecycleEnv {
	t.Helper()
	cli := getDockerClient(t)
	pullImage(t, cli, lifecycleOldImage)
	pullImage(t, cli, lifecycleNewImage)

	log := logrus.New()
	log.SetLevel(logrus.ErrorLevel)

	env := &lifecycleEnv{
		t:      t,
		cli:    cli,
		ctx:    context.Background(),
		log:    log,
		prefix: fmt.Sprintf("dockmon-lifecycle-%d", time.Now().UnixNano()),
	}
	t.Cleanup(env.removeAll)
	return env
}

func (e *lifecycleEnv) removeAll() {
	containers, err := e.cli.ContainerList(e.ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", e.prefix)),
	})
	if err != nil {
		e.t.Logf("cleanup list failed: %v", err)
		return
	}
	for _, c := range containers {
		if err := e.cli.ContainerRemove(e.ctx, c.ID, container.RemoveOptions{Force: true}); err != nil {
			e.t.Logf("cleanup remove %s failed: %v", c.ID[:12], err)
		}
	}
}

func (e *lifecycleEnv) name(suffix string) string {
	return e.prefix + "-" + suffix
}

type containerSpec struct {
	suffix      string
	networkMode string
	unhealthy   bool
	stopped     bool
}

func (e *lifecycleEnv) create(spec containerSpec) string {
	e.t.Helper()
	cfg := &container.Config{Image: lifecycleOldImage, Cmd: []string{"sleep", "600"}}
	if spec.unhealthy {
		cfg.Healthcheck = &container.HealthConfig{
			Test:     []string{"CMD-SHELL", "exit 1"},
			Interval: time.Second,
			Timeout:  time.Second,
			Retries:  1,
		}
	}
	hostCfg := &container.HostConfig{}
	if spec.networkMode != "" {
		hostCfg.NetworkMode = container.NetworkMode(spec.networkMode)
	}
	resp, err := e.cli.ContainerCreate(e.ctx, cfg, hostCfg, nil, nil, e.name(spec.suffix))
	if err != nil {
		e.t.Fatalf("create %s: %v", spec.suffix, err)
	}
	if !spec.stopped {
		if err := e.cli.ContainerStart(e.ctx, resp.ID, container.StartOptions{}); err != nil {
			e.t.Fatalf("start %s: %v", spec.suffix, err)
		}
	}
	return resp.ID
}

type updateRun struct {
	result *UpdateResult
	stages []string
}

func (e *lifecycleEnv) update(containerID, newImage string) updateRun {
	e.t.Helper()
	var mu sync.Mutex
	var stages []string

	options := DetectOptions(e.ctx, e.cli, e.log)
	options.OnProgress = func(event ProgressEvent) {
		mu.Lock()
		defer mu.Unlock()
		stages = append(stages, event.Stage)
	}

	result := NewUpdater(e.cli, e.log, options).Update(e.ctx, UpdateRequest{
		ContainerID:   containerID,
		NewImage:      newImage,
		StopTimeout:   1,
		HealthTimeout: 10,
	})
	return updateRun{result: result, stages: stages}
}

func (e *lifecycleEnv) inspectByName(suffix string) container.InspectResponse {
	e.t.Helper()
	inspect, err := e.cli.ContainerInspect(e.ctx, e.name(suffix))
	if err != nil {
		e.t.Fatalf("inspect %s: %v", suffix, err)
	}
	return inspect
}

func (e *lifecycleEnv) hasNetwork(containerID string) bool {
	e.t.Helper()
	exec, err := e.cli.ContainerExecCreate(e.ctx, containerID, container.ExecOptions{
		Cmd:          []string{"ip", "-o", "-4", "addr", "show"},
		AttachStdout: true,
		AttachStderr: true,
	})
	if err != nil {
		e.t.Fatalf("exec create: %v", err)
	}
	attach, err := e.cli.ContainerExecAttach(e.ctx, exec.ID, container.ExecAttachOptions{})
	if err != nil {
		e.t.Fatalf("exec attach: %v", err)
	}
	defer attach.Close()

	var stdout, stderr bytes.Buffer
	if _, err := stdcopy.StdCopy(&stdout, &stderr, attach.Reader); err != nil {
		e.t.Fatalf("exec read: %v", err)
	}
	for _, line := range strings.Split(stdout.String(), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[1] != "lo" {
			return true
		}
	}
	return false
}

func (e *lifecycleEnv) assertNoLeftovers(suffix string) {
	e.t.Helper()
	containers, err := e.cli.ContainerList(e.ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", e.name(suffix)+"-dockmon-")),
	})
	if err != nil {
		e.t.Fatalf("list leftovers: %v", err)
	}
	if len(containers) != 0 {
		e.t.Errorf("expected no backup or temp containers for %s, found %d", suffix, len(containers))
	}
}

func lastStage(stages []string) string {
	if len(stages) == 0 {
		return ""
	}
	return stages[len(stages)-1]
}

func containsStage(stages []string, stage string) bool {
	for _, s := range stages {
		if s == stage {
			return true
		}
	}
	return false
}

func TestLifecycle_ProviderSuccessRecreatesRunningDependent(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.Success {
		t.Fatalf("expected success, got error: %s", run.result.Error)
	}
	if len(run.result.FailedDependents) != 0 {
		t.Errorf("expected no failed dependents, got %v", run.result.FailedDependents)
	}
	if lastStage(run.stages) != StageCompleted || !containsStage(run.stages, StageDependents) {
		t.Errorf("unexpected stages: %v", run.stages)
	}

	provider := env.inspectByName("provider")
	if provider.ID == providerID {
		t.Error("expected the provider to get a new ID")
	}
	if provider.Config.Image != lifecycleNewImage || !provider.State.Running {
		t.Errorf("provider: image=%s running=%v", provider.Config.Image, provider.State.Running)
	}

	dependent := env.inspectByName("dependent")
	if dependent.ID == dependentID {
		t.Error("expected the dependent to be recreated")
	}
	if want := "container:" + provider.ID; string(dependent.HostConfig.NetworkMode) != want {
		t.Errorf("dependent network mode = %s, want %s", dependent.HostConfig.NetworkMode, want)
	}
	if dependent.Config.Image != lifecycleOldImage {
		t.Errorf("dependent should keep its image, got %s", dependent.Config.Image)
	}
	if !dependent.State.Running || !env.hasNetwork(dependent.ID) {
		t.Errorf("dependent should be running with a network, running=%v", dependent.State.Running)
	}
	env.assertNoLeftovers("provider")
	env.assertNoLeftovers("dependent")
}

func TestLifecycle_DependentFirstThenProvider(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	dependentRun := env.update(dependentID, lifecycleNewImage)
	if !dependentRun.result.Success {
		t.Fatalf("dependent update failed: %s", dependentRun.result.Error)
	}
	if provider := env.inspectByName("provider"); provider.ID != providerID || !provider.State.Running {
		t.Fatalf("the dependent's update must not touch its provider: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	if !env.hasNetwork(env.inspectByName("dependent").ID) {
		t.Fatal("dependent should have a network after its own update")
	}

	providerRun := env.update(providerID, lifecycleNewImage)
	if !providerRun.result.Success {
		t.Fatalf("provider update failed: %s", providerRun.result.Error)
	}
	if len(providerRun.result.FailedDependents) != 0 {
		t.Errorf("expected no failed dependents, got %v", providerRun.result.FailedDependents)
	}

	provider := env.inspectByName("provider")
	dependent := env.inspectByName("dependent")
	if dependent.Config.Image != lifecycleNewImage {
		t.Errorf("dependent should keep the image from its own update, got %s", dependent.Config.Image)
	}
	if want := "container:" + provider.ID; string(dependent.HostConfig.NetworkMode) != want {
		t.Errorf("dependent network mode = %s, want %s", dependent.HostConfig.NetworkMode, want)
	}
	if !dependent.State.Running || !env.hasNetwork(dependent.ID) {
		t.Errorf("dependent should be running with a network, running=%v", dependent.State.Running)
	}
}

func TestLifecycle_HealthFailureRestoresProvider(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.update(providerID, lifecycleNewImage)

	if run.result.Success || !run.result.RolledBack {
		t.Fatalf("expected a rolled back failure: success=%v rolledBack=%v", run.result.Success, run.result.RolledBack)
	}
	if !strings.Contains(run.result.Error, "health check failed") {
		t.Errorf("unexpected error: %s", run.result.Error)
	}
	if lastStage(run.stages) != StageRollback {
		t.Errorf("unexpected stages: %v", run.stages)
	}

	provider := env.inspectByName("provider")
	if provider.ID != providerID || provider.Config.Image != lifecycleOldImage || !provider.State.Running {
		t.Errorf("provider not restored: id=%s image=%s running=%v", provider.ID[:12], provider.Config.Image, provider.State.Running)
	}
	if dependent := env.inspectByName("dependent"); dependent.ID != dependentID {
		t.Errorf("rollback must keep the dependent's ID, got %s", dependent.ID[:12])
	}
	env.assertNoLeftovers("provider")
}

func TestLifecycle_HealthFailureLeavesStoppedProviderStopped(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true, stopped: true})

	run := env.update(providerID, lifecycleNewImage)

	if run.result.Success || !run.result.RolledBack {
		t.Fatalf("expected a rolled back failure: success=%v rolledBack=%v", run.result.Success, run.result.RolledBack)
	}
	provider := env.inspectByName("provider")
	if provider.ID != providerID || provider.State.Running {
		t.Errorf("provider should be restored and stopped: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	env.assertNoLeftovers("provider")
}

func TestLifecycle_PullFailureTouchesNothing(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.update(providerID, "dockmon-test.invalid/no-such-image:latest")

	if run.result.Success || run.result.RolledBack {
		t.Fatalf("expected a plain failure: success=%v rolledBack=%v", run.result.Success, run.result.RolledBack)
	}
	if lastStage(run.stages) != StageFailed || containsStage(run.stages, StageBackup) {
		t.Errorf("unexpected stages: %v", run.stages)
	}
	provider := env.inspectByName("provider")
	if provider.ID != providerID || !provider.State.Running {
		t.Errorf("provider must be untouched: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	dependent := env.inspectByName("dependent")
	if dependent.ID != dependentID || !env.hasNetwork(dependent.ID) {
		t.Errorf("dependent must be untouched: id=%s", dependent.ID[:12])
	}
}

func TestLifecycle_DependentUpdateFailsWhileProviderIsStopped(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	timeout := 1
	if err := env.cli.ContainerStop(env.ctx, providerID, container.StopOptions{Timeout: &timeout}); err != nil {
		t.Fatalf("stop provider: %v", err)
	}

	run := env.update(dependentID, lifecycleNewImage)

	if run.result.Success {
		t.Fatal("expected failure with the provider stopped")
	}
	if !strings.Contains(run.result.Error, "failed to start container") {
		t.Errorf("unexpected error: %s", run.result.Error)
	}
	if dependent := env.inspectByName("dependent"); dependent.ID != dependentID {
		t.Errorf("the dependent should keep its ID, got %s", dependent.ID[:12])
	}
	env.assertNoLeftovers("dependent")
}
