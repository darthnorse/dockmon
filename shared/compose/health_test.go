package compose

import "testing"

func TestIsServiceResultHealthy(t *testing.T) {
	tests := []struct {
		name    string
		service ServiceResult
		want    bool
	}{
		// Running containers are healthy
		{
			name:    "running status",
			service: ServiceResult{Status: "running"},
			want:    true,
		},
		{
			name:    "up status",
			service: ServiceResult{Status: "Up 5 minutes"},
			want:    true,
		},
		{
			name:    "healthy status",
			service: ServiceResult{Status: "Up 5 minutes (healthy)"},
			want:    true,
		},
		// Unhealthy takes precedence
		{
			name:    "unhealthy status",
			service: ServiceResult{Status: "Up 5 minutes (unhealthy)"},
			want:    false,
		},

		// One-shot containers with restart:no, exit 0 (Issue #110)
		{
			name: "restart:no exit 0 - success",
			service: ServiceResult{
				Status:        "Exited (0) 5 seconds ago",
				RestartPolicy: "no",
				ExitCode:      0,
			},
			want: true,
		},
		{
			name: "restart:no exit 1 - failure",
			service: ServiceResult{
				Status:        "Exited (1) 5 seconds ago",
				RestartPolicy: "no",
				ExitCode:      1,
			},
			want: false,
		},
		{
			name: "empty restart policy (default=no) exit 0 - success",
			service: ServiceResult{
				Status:        "Exited (0) 5 seconds ago",
				RestartPolicy: "",
				ExitCode:      0,
			},
			want: true,
		},

		// One-shot containers with restart:on-failure, exit 0 (Issue #110)
		{
			name: "restart:on-failure exit 0 - success",
			service: ServiceResult{
				Status:        "Exited (0) 5 seconds ago",
				RestartPolicy: "on-failure",
				ExitCode:      0,
			},
			want: true,
		},
		{
			name: "restart:on-failure exit 1 - failure",
			service: ServiceResult{
				Status:        "Exited (1) 5 seconds ago",
				RestartPolicy: "on-failure",
				ExitCode:      1,
			},
			want: false,
		},

		// Daemon containers with restart:always - any exit is failure
		{
			name: "restart:always exit 0 - failure",
			service: ServiceResult{
				Status:        "Exited (0) 5 seconds ago",
				RestartPolicy: "always",
				ExitCode:      0,
			},
			want: false,
		},
		{
			name: "restart:always exit 1 - failure",
			service: ServiceResult{
				Status:        "Exited (1) 5 seconds ago",
				RestartPolicy: "always",
				ExitCode:      1,
			},
			want: false,
		},

		// Daemon containers with restart:unless-stopped - any exit is failure
		{
			name: "restart:unless-stopped exit 0 - failure",
			service: ServiceResult{
				Status:        "Exited (0) 5 seconds ago",
				RestartPolicy: "unless-stopped",
				ExitCode:      0,
			},
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := IsServiceResultHealthy(tt.service)
			if got != tt.want {
				t.Errorf("IsServiceResultHealthy() = %v, want %v (status=%q, policy=%q, exit=%d)",
					got, tt.want, tt.service.Status, tt.service.RestartPolicy, tt.service.ExitCode)
			}
		})
	}
}
