package handlers

import (
	"testing"

	dockerTypes "github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
)

// newTestSelfUpdateHandler builds a minimal handler for unit-testing methods
// that only read pure-function inputs - no Docker daemon, no WebSocket.
//
// Only h.log is populated. If a test exercises a method that reaches into
// h.dockerClient, h.sendEvent, h.stopSignal, h.myContainerID, or h.dataDir,
// it will nil-deref. Tests in this file may only call methods that read
// h.log; anything else needs a fuller fixture (or a mocked dependency).
func newTestSelfUpdateHandler() *SelfUpdateHandler {
	log := logrus.New()
	log.SetLevel(logrus.PanicLevel) // silence test output
	return &SelfUpdateHandler{
		log: log,
	}
}

// TestCloneContainerConfig_StripsInheritedImageLabels verifies that labels
// inherited from the OLD image (e.g. org.opencontainers.image.version) are
// removed when cloning config for the new container, so the NEW image's
// labels can take effect at inspect time.
//
// Regression test for: agent containers showing stale OCI version label
// (e.g. "1.0.4-amd64") after self-update because the old image's labels
// were copied verbatim into the new container.
func TestCloneContainerConfig_StripsInheritedImageLabels(t *testing.T) {
	h := newTestSelfUpdateHandler()

	oldImageLabels := map[string]string{
		"org.opencontainers.image.version": "1.0.4-amd64",
		"org.opencontainers.image.title":   "DockMon Agent",
	}

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "ghcr.io/darthnorse/dockmon-agent:1.0.4",
			Labels: map[string]string{
				// Inherited from old image - should be stripped:
				"org.opencontainers.image.version": "1.0.4-amd64",
				"org.opencontainers.image.title":   "DockMon Agent",
				// User-added - should be preserved:
				"com.example.deployed-by": "ansible",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "ghcr.io/darthnorse/dockmon-agent:1.0.9", oldImageLabels, nil)

	if _, present := newConfig.Labels["org.opencontainers.image.version"]; present {
		t.Errorf("expected inherited OCI version label to be stripped, got %q",
			newConfig.Labels["org.opencontainers.image.version"])
	}
	if _, present := newConfig.Labels["org.opencontainers.image.title"]; present {
		t.Error("expected inherited OCI title label to be stripped")
	}
	if got := newConfig.Labels["com.example.deployed-by"]; got != "ansible" {
		t.Errorf("expected user label preserved, got %q", got)
	}
	if newConfig.Image != "ghcr.io/darthnorse/dockmon-agent:1.0.9" {
		t.Errorf("expected new image set, got %q", newConfig.Image)
	}
}

// TestCloneContainerConfig_NilOldImageLabelsKeepsAllContainerLabels verifies
// graceful degradation: if we can't inspect the old image, we should
// preserve the existing pre-fix behavior (keep all labels) rather than
// dropping legitimate user labels.
func TestCloneContainerConfig_NilOldImageLabelsKeepsAllContainerLabels(t *testing.T) {
	h := newTestSelfUpdateHandler()

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "ghcr.io/darthnorse/dockmon-agent:1.0.4",
			Labels: map[string]string{
				"com.example.user-label":           "important",
				"org.opencontainers.image.version": "1.0.4-amd64",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "ghcr.io/darthnorse/dockmon-agent:1.0.9", nil, nil)

	if got := newConfig.Labels["com.example.user-label"]; got != "important" {
		t.Errorf("expected user label preserved with nil oldImageLabels, got %q", got)
	}
	if got := newConfig.Labels["org.opencontainers.image.version"]; got != "1.0.4-amd64" {
		t.Errorf("expected fallback to keep all labels when oldImageLabels nil, got %q", got)
	}
}

// TestCloneContainerConfig_UserOverrideOfImageLabelPreserved verifies that
// when the user explicitly set a label that *also happens to exist* in the
// image with a different value, the user's value is kept. This matches
// ExtractUserLabels' "value differs from image default" rule.
func TestCloneContainerConfig_UserOverrideOfImageLabelPreserved(t *testing.T) {
	h := newTestSelfUpdateHandler()

	oldImageLabels := map[string]string{
		"maintainer": "image-author@example.com",
	}

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "example/img:1",
			Labels: map[string]string{
				"maintainer": "ops-team@my-org",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "example/img:2", oldImageLabels, nil)

	if got := newConfig.Labels["maintainer"]; got != "ops-team@my-org" {
		t.Errorf("expected user override preserved, got %q", got)
	}
}

// TestCloneContainerConfig_StripsInheritedImageEnv verifies that env vars
// inherited from the OLD image's ENV directives are removed when cloning
// config for the new container, so the NEW image's ENV directives take
// effect on the recreated container.
//
// Regression test for Issue #218: app inside container reports stale version
// from APP_VERSION env var because the old image's ENV value was copied
// verbatim into the new container, shadowing the new image's APP_VERSION.
func TestCloneContainerConfig_StripsInheritedImageEnv(t *testing.T) {
	h := newTestSelfUpdateHandler()

	oldImageEnv := []string{
		"APP_VERSION=v3.0.0",
		"PATH=/usr/local/bin:/usr/bin:/bin",
	}

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "example/app:v3.0.0",
			Env: []string{
				// Inherited from old image - should be stripped:
				"APP_VERSION=v3.0.0",
				"PATH=/usr/local/bin:/usr/bin:/bin",
				// User-added - should be preserved:
				"DB_HOST=prod-db",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "example/app:v3.0.3", nil, oldImageEnv)

	for _, entry := range newConfig.Env {
		if entry == "APP_VERSION=v3.0.0" {
			t.Errorf("expected inherited APP_VERSION env to be stripped, found %q in newConfig.Env", entry)
		}
		if entry == "PATH=/usr/local/bin:/usr/bin:/bin" {
			t.Errorf("expected inherited PATH env to be stripped, found %q in newConfig.Env", entry)
		}
	}

	foundDBHost := false
	for _, entry := range newConfig.Env {
		if entry == "DB_HOST=prod-db" {
			foundDBHost = true
			break
		}
	}
	if !foundDBHost {
		t.Errorf("expected user env DB_HOST=prod-db preserved, got %v", newConfig.Env)
	}
}

// TestCloneContainerConfig_NilOldImageEnvKeepsAllContainerEnv verifies
// graceful degradation: if we can't inspect the old image's env, we should
// preserve the existing pre-fix behavior (keep all env) rather than
// dropping legitimate user env.
func TestCloneContainerConfig_NilOldImageEnvKeepsAllContainerEnv(t *testing.T) {
	h := newTestSelfUpdateHandler()

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "example/app:v3.0.0",
			Env: []string{
				"APP_VERSION=v3.0.0",
				"DB_HOST=prod-db",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "example/app:v3.0.3", nil, nil)

	if len(newConfig.Env) != 2 {
		t.Fatalf("expected fallback to keep all env entries when oldImageEnv nil, got %v", newConfig.Env)
	}
}

// TestCloneContainerConfig_UserOverrideOfImageEnvPreserved verifies that
// when the user explicitly set an env var that *also happens to exist* in
// the image with a different value, the user's value is kept. Matches
// ExtractUserEnv's "value differs from image default" rule.
func TestCloneContainerConfig_UserOverrideOfImageEnvPreserved(t *testing.T) {
	h := newTestSelfUpdateHandler()

	oldImageEnv := []string{"LOG_LEVEL=info"}

	inspect := &dockerTypes.ContainerJSON{
		Config: &container.Config{
			Image: "example/img:1",
			Env: []string{
				"LOG_LEVEL=debug",
			},
		},
	}

	newConfig := h.cloneContainerConfig(inspect, "example/img:2", nil, oldImageEnv)

	foundOverride := false
	for _, entry := range newConfig.Env {
		if entry == "LOG_LEVEL=debug" {
			foundOverride = true
			break
		}
	}
	if !foundOverride {
		t.Errorf("expected user override LOG_LEVEL=debug preserved, got %v", newConfig.Env)
	}
}
