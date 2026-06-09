package compose

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWriteStackEnvFilesWritesAll(t *testing.T) {
	dir := t.TempDir()
	files := map[string]string{".env": "A=1\n", ".db.env": "P=secret\n"}
	if err := WriteStackEnvFiles(dir, "myapp", files); err != nil {
		t.Fatalf("WriteStackEnvFiles: %v", err)
	}
	for name, want := range files {
		got, err := os.ReadFile(filepath.Join(dir, "myapp", name))
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if string(got) != want {
			t.Errorf("%s = %q, want %q", name, got, want)
		}
	}
}

func TestWriteStackEnvFilesRejectsUnsafeName(t *testing.T) {
	dir := t.TempDir()
	err := WriteStackEnvFiles(dir, "myapp", map[string]string{"../escape.env": "X=1"})
	if err == nil {
		t.Fatal("expected error for unsafe env filename, got nil")
	}
	if _, statErr := os.Stat(filepath.Join(filepath.Dir(dir), "escape.env")); statErr == nil {
		t.Fatal("unsafe file escaped the stack directory")
	}
}
