package compose

import (
	"os"
	"path/filepath"
	"testing"
)

// writeStackEnv mirrors the logic Deploy uses: EnvFiles wins; EnvFileContent
// is the legacy single-.env fallback. This test pins that precedence.
func TestEnvFilesPrecedenceHelper(t *testing.T) {
	dir := t.TempDir()
	if _, err := WriteStackComposeFile(dir, "p", "services: {}\n"); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{".env": "A=1\n", ".db.env": "B=2\n"}
	if err := WriteStackEnvFiles(dir, "p", files); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(filepath.Join(dir, "p", ".db.env"))
	if string(got) != "B=2\n" {
		t.Fatalf(".db.env = %q", got)
	}
}
