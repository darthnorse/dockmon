package compose

import (
	"os"
	"path/filepath"
	"testing"
)

// TestWriteStackEnvFilesRejectsSymlinkTarget verifies that WriteStackEnvFiles
// returns an error when the target filename resolves to an existing symlink
// inside the stack directory, and does NOT write through the symlink to the
// linked target (O_NOFOLLOW protection).
func TestWriteStackEnvFilesRejectsSymlinkTarget(t *testing.T) {
	stacks := t.TempDir()
	outside := t.TempDir()

	// Create the stack directory manually so we can plant a symlink inside it.
	stackDir := filepath.Join(stacks, "myapp")
	if err := os.MkdirAll(stackDir, 0755); err != nil {
		t.Fatalf("mkdir stackDir: %v", err)
	}

	// Write a known payload to the outside file.
	outsideFile := filepath.Join(outside, "secret.txt")
	const originalContent = "ORIGINAL"
	if err := os.WriteFile(outsideFile, []byte(originalContent), 0644); err != nil {
		t.Fatalf("write outside file: %v", err)
	}

	// Plant a symlink named .db.env inside the stack dir pointing outside.
	symlinkPath := filepath.Join(stackDir, ".db.env")
	if err := os.Symlink(outsideFile, symlinkPath); err != nil {
		t.Fatalf("create symlink: %v", err)
	}

	// Attempt to write through the symlink target name — must fail.
	err := WriteStackEnvFiles(stacks, "myapp", map[string]string{".db.env": "PWNED"})
	if err == nil {
		t.Fatal("expected error when writing to a symlinked env filename, got nil")
	}

	// Verify the outside file was NOT overwritten.
	got, rerr := os.ReadFile(outsideFile)
	if rerr != nil {
		t.Fatalf("read outside file: %v", rerr)
	}
	if string(got) != originalContent {
		t.Errorf("outside file content = %q; want %q (was overwritten through symlink!)", got, originalContent)
	}
}

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
