package update

import "testing"

func TestIsExitAcceptable(t *testing.T) {
	tests := []struct {
		name          string
		restartPolicy string
		exitCode      int
		want          bool
	}{
		// restart: no - exit 0 should be acceptable
		{"no policy, exit 0", "no", 0, true},
		{"no policy, exit 1", "no", 1, false},
		{"no policy, exit 137", "no", 137, false},

		// empty string (default) - same as "no"
		{"empty policy, exit 0", "", 0, true},
		{"empty policy, exit 1", "", 1, false},

		// restart: on-failure - exit 0 should be acceptable (Docker semantics)
		{"on-failure, exit 0", "on-failure", 0, true},
		{"on-failure, exit 1", "on-failure", 1, false},
		{"on-failure, exit 137", "on-failure", 137, false},

		// restart: always - any exit should NOT be acceptable
		{"always, exit 0", "always", 0, false},
		{"always, exit 1", "always", 1, false},

		// restart: unless-stopped - any exit should NOT be acceptable
		{"unless-stopped, exit 0", "unless-stopped", 0, false},
		{"unless-stopped, exit 1", "unless-stopped", 1, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isExitAcceptable(tt.restartPolicy, tt.exitCode)
			if got != tt.want {
				t.Errorf("isExitAcceptable(%q, %d) = %v, want %v",
					tt.restartPolicy, tt.exitCode, got, tt.want)
			}
		})
	}
}
