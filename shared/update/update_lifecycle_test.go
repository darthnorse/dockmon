//go:build integration

package update

import (
	"bytes"
	"context"
	"fmt"
	"slices"
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
	return e.updateWithHook(containerID, newImage, nil)
}

func (e *lifecycleEnv) updateWithHook(containerID, newImage string, onStage func(stage string)) updateRun {
	e.t.Helper()
	var mu sync.Mutex
	var stages []string

	options := DetectOptions(e.ctx, e.cli, e.log)
	options.OnProgress = func(event ProgressEvent) {
		mu.Lock()
		stages = append(stages, event.Stage)
		mu.Unlock()
		if onStage != nil {
			onStage(event.Stage)
		}
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

func (e *lifecycleEnv) stop(containerID string) {
	e.t.Helper()
	timeout := 1
	if err := e.cli.ContainerStop(e.ctx, containerID, container.StopOptions{Timeout: &timeout}); err != nil {
		e.t.Fatalf("stop: %v", err)
	}
}

func (e *lifecycleEnv) exec(containerID string, cmd ...string) {
	e.t.Helper()
	exec, err := e.cli.ContainerExecCreate(e.ctx, containerID, container.ExecOptions{Cmd: cmd})
	if err != nil {
		e.t.Fatalf("exec create: %v", err)
	}
	if err := e.cli.ContainerExecStart(e.ctx, exec.ID, container.ExecStartOptions{}); err != nil {
		e.t.Fatalf("exec start: %v", err)
	}
	time.Sleep(200 * time.Millisecond)
}

func assertNamed(t *testing.T, result *UpdateResult, name string) {
	t.Helper()
	if !slices.Contains(result.FailedDependents, name) {
		t.Errorf("expected %s in FailedDependents, got %v", name, result.FailedDependents)
	}
	if !strings.Contains(result.Error, name) {
		t.Errorf("expected %s in the error, got: %s", name, result.Error)
	}
}

func TestLifecycle_RollbackRestoresDependentNetwork(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.RolledBack {
		t.Fatalf("expected a rollback, got: %s", run.result.Error)
	}
	if len(run.result.FailedDependents) != 0 {
		t.Errorf("expected every dependent recovered, got %v", run.result.FailedDependents)
	}
	dependent := env.inspectByName("dependent")
	if dependent.ID != dependentID {
		t.Errorf("rollback must keep the dependent's ID, got %s", dependent.ID[:12])
	}
	if !dependent.State.Running || !env.hasNetwork(dependentID) {
		t.Errorf("dependent should have its network back, running=%v", dependent.State.Running)
	}
}

func TestLifecycle_RollbackLeavesStoppedDependentStopped(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID, stopped: true})

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.RolledBack {
		t.Fatalf("expected a rollback, got: %s", run.result.Error)
	}
	if env.inspectByName("dependent").State.Running {
		t.Error("a stopped dependent must stay stopped")
	}
	if len(run.result.FailedDependents) != 0 {
		t.Errorf("a stopped dependent isn't a failure, got %v", run.result.FailedDependents)
	}
}

func TestLifecycle_RollbackRecoversDependentCreatedDuringUpdate(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	var lateID string

	run := env.updateWithHook(providerID, lifecycleNewImage, func(stage string) {
		if stage == StageBackup {
			lateID = env.create(containerSpec{suffix: "late", networkMode: "container:" + providerID})
		}
	})

	if !run.result.RolledBack {
		t.Fatalf("expected a rollback, got: %s", run.result.Error)
	}
	if lateID == "" || !env.inspectByName("late").State.Running || !env.hasNetwork(lateID) {
		t.Error("a dependent created before the provider stopped should be recovered")
	}
}

func TestLifecycle_RollbackRecoversDependentThatExitedWithItsProvider(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.updateWithHook(providerID, lifecycleNewImage, func(stage string) {
		if stage == StageCreating {
			env.stop(dependentID)
		}
	})

	if !run.result.RolledBack {
		t.Fatalf("expected a rollback, got: %s", run.result.Error)
	}
	if !env.inspectByName("dependent").State.Running || !env.hasNetwork(dependentID) {
		t.Error("a dependent that was running before the update should be recovered")
	}
}

func TestLifecycle_StartFailureRollsBackAndRecoversDependent(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.updateWithHook(providerID, lifecycleNewImage, func(stage string) {
		if stage == StageStarting {
			created, err := env.cli.ContainerInspect(env.ctx, env.name("provider"))
			if err != nil {
				t.Fatalf("inspect new provider: %v", err)
			}
			if err := env.cli.ContainerRemove(env.ctx, created.ID, container.RemoveOptions{Force: true}); err != nil {
				t.Fatalf("remove new provider: %v", err)
			}
		}
	})

	if run.result.Success || !run.result.RolledBack {
		t.Fatalf("expected a rolled back failure: success=%v rolledBack=%v error=%s", run.result.Success, run.result.RolledBack, run.result.Error)
	}
	if lastStage(run.stages) != StageRollback {
		t.Errorf("unexpected stages: %v", run.stages)
	}
	provider := env.inspectByName("provider")
	if provider.ID != providerID || !provider.State.Running {
		t.Errorf("provider not restored: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	if !env.hasNetwork(dependentID) {
		t.Error("dependent should have its network back")
	}
}

func TestLifecycle_CreateFailureRollsBackAndRecoversDependent(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.updateWithHook(providerID, lifecycleNewImage, func(stage string) {
		if stage == StageCreating {
			env.create(containerSpec{suffix: "provider", stopped: true})
		}
	})

	if run.result.Success || !run.result.RolledBack {
		t.Fatalf("expected a rolled back failure: success=%v rolledBack=%v error=%s", run.result.Success, run.result.RolledBack, run.result.Error)
	}
	provider := env.inspectByName("provider")
	if provider.ID != providerID || !provider.State.Running {
		t.Errorf("provider not restored: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	if !env.hasNetwork(dependentID) {
		t.Error("dependent should have its network back")
	}
}

func TestLifecycle_FailedRestoreNamesDependents(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	run := env.updateWithHook(providerID, lifecycleNewImage, func(stage string) {
		if stage == StageHealthCheck {
			if err := env.cli.ContainerRemove(env.ctx, providerID, container.RemoveOptions{Force: true}); err != nil {
				t.Fatalf("remove backup: %v", err)
			}
		}
	})

	if run.result.Success || run.result.RolledBack {
		t.Fatalf("a failed restore isn't a rollback: success=%v rolledBack=%v", run.result.Success, run.result.RolledBack)
	}
	if !strings.Contains(run.result.Error, "rollback also failed") {
		t.Errorf("unexpected error: %s", run.result.Error)
	}
	assertNamed(t, run.result, env.name("dependent"))
}

func TestLifecycle_UnrestartableDependentIsNamedAndOthersRecover(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	brokenID := env.create(containerSpec{suffix: "broken", networkMode: "container:" + providerID})
	healthyID := env.create(containerSpec{suffix: "healthy", networkMode: "container:" + providerID})
	env.exec(brokenID, "rm", "/bin/sleep")

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.RolledBack {
		t.Fatalf("restoring the provider still counts as a rollback: %s", run.result.Error)
	}
	assertNamed(t, run.result, env.name("broken"))
	if !env.hasNetwork(healthyID) {
		t.Error("one failed restart must not stop the others")
	}
}

func TestLifecycle_RollbackOfStoppedProviderNamesRunningDependent(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider", unhealthy: true})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})
	env.stop(providerID)

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.RolledBack {
		t.Fatalf("expected a rollback, got: %s", run.result.Error)
	}
	assertNamed(t, run.result, env.name("dependent"))
	dependent := env.inspectByName("dependent")
	if dependent.ID != dependentID {
		t.Errorf("the dependent should be left as it is, got %s", dependent.ID[:12])
	}
}

func TestLifecycle_SuccessWithStoppedProviderLeavesDependentStoppedAndNamed(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})
	env.stop(providerID)

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.Success {
		t.Fatalf("expected success, got: %s", run.result.Error)
	}
	if len(run.result.FailedDependents) != 1 || run.result.FailedDependents[0] != env.name("dependent") {
		t.Errorf("expected the dependent named, got %v", run.result.FailedDependents)
	}
	provider := env.inspectByName("provider")
	dependent := env.inspectByName("dependent")
	if provider.State.Running || dependent.State.Running {
		t.Errorf("both should be stopped: provider=%v dependent=%v", provider.State.Running, dependent.State.Running)
	}
	if want := "container:" + provider.ID; string(dependent.HostConfig.NetworkMode) != want {
		t.Errorf("dependent network mode = %s, want %s", dependent.HostConfig.NetworkMode, want)
	}
	env.assertNoLeftovers("dependent")
}

func TestLifecycle_SuccessLeavesStoppedDependentStopped(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID, stopped: true})

	run := env.update(providerID, lifecycleNewImage)

	if !run.result.Success {
		t.Fatalf("expected success, got: %s", run.result.Error)
	}
	if len(run.result.FailedDependents) != 0 {
		t.Errorf("a stopped dependent isn't a failure, got %v", run.result.FailedDependents)
	}
	provider := env.inspectByName("provider")
	dependent := env.inspectByName("dependent")
	if dependent.State.Running {
		t.Error("a stopped dependent must stay stopped")
	}
	if want := "container:" + provider.ID; string(dependent.HostConfig.NetworkMode) != want {
		t.Errorf("dependent network mode = %s, want %s", dependent.HostConfig.NetworkMode, want)
	}
}

func TestLifecycle_BackupRenameFailureRecovers(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	dependentID := env.create(containerSpec{suffix: "dependent", networkMode: "container:" + providerID})

	now := time.Now().Unix()
	for ts := now; ts < now+40; ts++ {
		env.create(containerSpec{suffix: fmt.Sprintf("provider-dockmon-backup-%d", ts), stopped: true})
	}

	run := env.update(providerID, lifecycleNewImage)

	if run.result.Success || run.result.RolledBack {
		t.Fatalf("expected a plain failure: success=%v rolledBack=%v error=%s", run.result.Success, run.result.RolledBack, run.result.Error)
	}
	provider := env.inspectByName("provider")
	if provider.ID != providerID || !provider.State.Running {
		t.Errorf("provider should be running again: id=%s running=%v", provider.ID[:12], provider.State.Running)
	}
	if !env.hasNetwork(dependentID) {
		t.Error("dependent should have its network back")
	}
}

func TestLifecycle_BackupRenameFailureReportsAFailedRestart(t *testing.T) {
	env := newLifecycleEnv(t)
	providerID := env.create(containerSpec{suffix: "provider"})
	env.exec(providerID, "rm", "/bin/sleep")

	now := time.Now().Unix()
	for ts := now; ts < now+40; ts++ {
		env.create(containerSpec{suffix: fmt.Sprintf("provider-dockmon-backup-%d", ts), stopped: true})
	}

	run := env.update(providerID, lifecycleNewImage)

	if run.result.Success {
		t.Fatal("expected failure")
	}
	if env.inspectByName("provider").State.Running {
		t.Fatal("the provider should have failed to restart")
	}
	if !strings.Contains(run.result.Error, "restart also failed") {
		t.Errorf("the error must say the provider is now stopped, got: %s", run.result.Error)
	}
}
