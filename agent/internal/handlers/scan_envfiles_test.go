package handlers

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/sirupsen/logrus"
)

// newTestScanHandler returns a minimal ScanHandler suitable for unit tests.
func newTestScanHandler() *ScanHandler {
	log := logrus.New()
	log.SetOutput(os.Stderr)
	return NewScanHandler(log, func(_ string, _ interface{}) error { return nil })
}

// makeCompose writes a minimal compose file that references the given env_file names.
func makeCompose(t *testing.T, dir string, envFileNames ...string) string {
	t.Helper()
	var refs strings.Builder
	for _, n := range envFileNames {
		refs.WriteString("      - " + n + "\n")
	}
	composeSrc := "services:\n  app:\n    image: alpine\n    env_file:\n" + refs.String()
	composePath := filepath.Join(dir, "docker-compose.yml")
	if err := os.WriteFile(composePath, []byte(composeSrc), 0644); err != nil {
		t.Fatalf("write compose: %v", err)
	}
	return composePath
}

// TestReadComposeFileSkipsSymlinkedEnvFile verifies that ReadComposeFile does
// not return the content of a symlinked env file and adds its name to
// SkippedEnvFiles instead.
func TestReadComposeFileSkipsSymlinkedEnvFile(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()

	// Write a secret outside file.
	outsideFile := filepath.Join(outside, "secret.env")
	const secret = "SECRET=pwned"
	if err := os.WriteFile(outsideFile, []byte(secret), 0644); err != nil {
		t.Fatalf("write outside: %v", err)
	}

	// Plant a symlink named .db.env in the compose dir pointing outside.
	if err := os.Symlink(outsideFile, filepath.Join(dir, ".db.env")); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	composePath := makeCompose(t, dir, ".db.env")

	h := newTestScanHandler()
	res := h.ReadComposeFile(context.Background(), ReadComposeFileRequest{Path: composePath})

	if !res.Success {
		t.Fatalf("ReadComposeFile failed: %s", res.Error)
	}
	if _, ok := res.EnvFiles[".db.env"]; ok {
		t.Errorf("EnvFiles contains .db.env (symlink content was returned); want it absent")
	}
	if !contains(res.SkippedEnvFiles, ".db.env") {
		t.Errorf("SkippedEnvFiles = %v; want .db.env listed", res.SkippedEnvFiles)
	}
}

// TestReadComposeFileSkipsOversizedEnvFile verifies that ReadComposeFile skips
// an env file whose size exceeds maxFileSize and lists it in SkippedEnvFiles.
func TestReadComposeFileSkipsOversizedEnvFile(t *testing.T) {
	dir := t.TempDir()

	// Write a file just over 1 MB.
	bigPath := filepath.Join(dir, ".big.env")
	const oversized = 1024*1024 + 1
	if err := os.WriteFile(bigPath, make([]byte, oversized), 0644); err != nil {
		t.Fatalf("write big file: %v", err)
	}

	composePath := makeCompose(t, dir, ".big.env")

	h := newTestScanHandler()
	res := h.ReadComposeFile(context.Background(), ReadComposeFileRequest{Path: composePath})

	if !res.Success {
		t.Fatalf("ReadComposeFile failed: %s", res.Error)
	}
	if _, ok := res.EnvFiles[".big.env"]; ok {
		t.Errorf("EnvFiles contains .big.env (oversized content was returned); want it absent")
	}
	if !contains(res.SkippedEnvFiles, ".big.env") {
		t.Errorf("SkippedEnvFiles = %v; want .big.env listed", res.SkippedEnvFiles)
	}
}

// contains reports whether s is an element of slice.
func contains(slice []string, s string) bool {
	for _, v := range slice {
		if v == s {
			return true
		}
	}
	return false
}

func TestParseEnvFileRefs(t *testing.T) {
	compose := `
services:
  app:
    env_file: .app.env
  db:
    env_file:
      - .db.env
      - path: ./extra.env
      - ../escape.env
      - /abs/x.env
`
	captured, skipped := parseEnvFileRefs([]byte(compose))
	sort.Strings(captured)
	want := []string{".app.env", ".db.env", "extra.env"}
	if !reflect.DeepEqual(captured, want) {
		t.Errorf("captured = %v, want %v", captured, want)
	}
	sort.Strings(skipped)
	wantSkip := []string{"../escape.env", "/abs/x.env"}
	if !reflect.DeepEqual(skipped, wantSkip) {
		t.Errorf("skipped = %v, want %v", skipped, wantSkip)
	}
}

func TestParseEnvFileRefsSingleLongForm(t *testing.T) {
	compose := `
services:
  solo:
    env_file:
      path: ./solo.env
      required: false
`
	captured, _ := parseEnvFileRefs([]byte(compose))
	if len(captured) != 1 || captured[0] != "solo.env" {
		t.Fatalf("captured = %v, want [solo.env]", captured)
	}
}

func TestParseEnvFileRefsMalformed(t *testing.T) {
	captured, skipped := parseEnvFileRefs([]byte(":\n  bad: ["))
	if captured != nil || skipped != nil {
		t.Fatalf("malformed -> (%v, %v), want (nil, nil)", captured, skipped)
	}
}

func TestParseEnvFileRefsDedup(t *testing.T) {
	compose := `
services:
  a:
    env_file: .shared.env
  b:
    env_file: .shared.env
`
	captured, _ := parseEnvFileRefs([]byte(compose))
	if len(captured) != 1 || captured[0] != ".shared.env" {
		t.Fatalf("captured = %v, want [.shared.env]", captured)
	}
}
