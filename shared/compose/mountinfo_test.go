package compose

import (
	"strings"
	"testing"
)

func TestParseMountInfoLine(t *testing.T) {
	tests := []struct {
		name          string
		line          string
		wantRoot      string
		wantMountPt   string
		wantOK        bool
	}{
		{
			name:        "bind mount from host path",
			line:        "123 45 0:78 /opt/dockmon/data /app/data rw,relatime shared:1 - ext4 /dev/sda1 rw",
			wantRoot:    "/opt/dockmon/data",
			wantMountPt: "/app/data",
			wantOK:      true,
		},
		{
			name:        "named volume path",
			line:        "789 45 0:90 /var/lib/docker/volumes/dockmon_data/_data /app/data rw,relatime - ext4 /dev/sda1 rw",
			wantRoot:    "/var/lib/docker/volumes/dockmon_data/_data",
			wantMountPt: "/app/data",
			wantOK:      true,
		},
		{
			name:        "root filesystem mount",
			line:        "1 0 259:1 / / rw,relatime - ext4 /dev/root rw",
			wantRoot:    "/",
			wantMountPt: "/",
			wantOK:      true,
		},
		{
			name: "optional fields present (multiple shared/master tags)",
			line: "100 50 0:22 /src /dst rw,nosuid,nodev,relatime shared:1 master:2 " +
				"- tmpfs tmpfs rw,mode=755",
			wantRoot:    "/src",
			wantMountPt: "/dst",
			wantOK:      true,
		},
		{
			name:        "no optional fields",
			line:        "42 10 0:5 /a /b rw - sysfs sysfs rw",
			wantRoot:    "/a",
			wantMountPt: "/b",
			wantOK:      true,
		},
		{
			name:        "missing dash separator - malformed",
			line:        "1 2 3:4 /a /b rw relatime ext4 dev rw",
			wantRoot:    "",
			wantMountPt: "",
			wantOK:      false,
		},
		{
			name:        "too few fields",
			line:        "1 2 3:4",
			wantRoot:    "",
			wantMountPt: "",
			wantOK:      false,
		},
		{
			name:        "empty line",
			line:        "",
			wantRoot:    "",
			wantMountPt: "",
			wantOK:      false,
		},
		{
			name:        "kernel escape sequences in path (space as \\040)",
			line:        `50 10 0:5 /path\040with\040space /mnt rw - ext4 /dev/sda1 rw`,
			wantRoot:    "/path with space",
			wantMountPt: "/mnt",
			wantOK:      true,
		},
		{
			name:        "trailing escape sequence at end of root path",
			line:        `50 10 0:5 /trailing\040 /mnt rw - ext4 /dev/sda1 rw`,
			wantRoot:    "/trailing ",
			wantMountPt: "/mnt",
			wantOK:      true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			root, mnt, ok := parseMountInfoLine(tc.line)
			if ok != tc.wantOK {
				t.Fatalf("ok=%v, want %v", ok, tc.wantOK)
			}
			if !ok {
				return
			}
			if root != tc.wantRoot {
				t.Errorf("root=%q, want %q", root, tc.wantRoot)
			}
			if mnt != tc.wantMountPt {
				t.Errorf("mount_point=%q, want %q", mnt, tc.wantMountPt)
			}
		})
	}
}

func TestDiscoverHostPathFromReader(t *testing.T) {
	tests := []struct {
		name          string
		mountinfo     string
		containerPath string
		want          string
	}{
		{
			name: "bind mount covers stacks dir",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /opt/dockmon/data /app/data rw - ext4 /dev/sda1 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/opt/dockmon/data/stacks",
		},
		{
			name: "named volume covers stacks dir",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /var/lib/docker/volumes/dockmon_data/_data /app/data rw - ext4 /dev/sda1 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/var/lib/docker/volumes/dockmon_data/_data/stacks",
		},
		{
			name: "exact mount point match (no suffix to append)",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /opt/dockmon/data /app/data rw - ext4 /dev/sda1 rw\n",
			containerPath: "/app/data",
			want:          "/opt/dockmon/data",
		},
		{
			name: "no mount covers path (on host root only)",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"200 1 0:50 /var/log /var/log rw - ext4 /dev/sda2 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/app/data/stacks",
		},
		{
			name: "longest-prefix wins over shorter mount",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /host/data /app/data rw - ext4 /dev/sda1 rw\n" +
				"101 1 0:51 /host/stacks /app/data/stacks rw - ext4 /dev/sda2 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/host/stacks",
		},
		{
			name: "longest-prefix with suffix",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /host/data /app/data rw - ext4 /dev/sda1 rw\n" +
				"101 1 0:51 /host/stacks /app/data/stacks rw - ext4 /dev/sda2 rw\n",
			containerPath: "/app/data/stacks/myproj",
			want:          "/host/stacks/myproj",
		},
		{
			name:          "empty mountinfo returns input",
			mountinfo:     "",
			containerPath: "/app/data/stacks",
			want:          "/app/data/stacks",
		},
		{
			name: "malformed lines skipped gracefully",
			mountinfo: "garbage line with no structure\n" +
				"1 2 3:4\n" +
				"100 1 0:50 /opt/dockmon/data /app/data rw - ext4 /dev/sda1 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/opt/dockmon/data/stacks",
		},
		{
			name: "sibling path under same parent is not matched",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /host/data-other /app/data-other rw - ext4 /dev/sda1 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/app/data/stacks",
		},
		{
			name: "root filesystem alone does not rewrite",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n",
			// When only `/` is mounted, the kernel reports root=/ for the
			// containerPath which would trivially rewrite to itself. Keep
			// the input unchanged to avoid confusing "/ -> /" no-op rewrites.
			containerPath: "/app/data/stacks",
			want:          "/app/data/stacks",
		},
		{
			name: "later duplicate mount wins (matches kernel semantics)",
			mountinfo: "1 0 259:1 / / rw - ext4 /dev/root rw\n" +
				"100 1 0:50 /first/path /app/data rw - ext4 /dev/sda1 rw\n" +
				"200 1 0:51 /second/path /app/data rw - ext4 /dev/sda2 rw\n",
			containerPath: "/app/data/stacks",
			want:          "/second/path/stacks",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := discoverHostPathFromReader(strings.NewReader(tc.mountinfo), tc.containerPath)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.want {
				t.Errorf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestDiscoverHostPath_UnreadableFile(t *testing.T) {
	// Verify the high-level helper handles a missing /proc/self/mountinfo.
	// This is the non-containerized bare-metal scenario on non-Linux or
	// stripped systems.
	got, err := discoverHostPathFromFile("/nonexistent/path/mountinfo", "/app/data/stacks")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// On missing file, should fall back to input path (running on host,
	// or /proc not available).
	if got != "/app/data/stacks" {
		t.Errorf("got %q, want input path", got)
	}
}
