package compose

import (
	"testing"

	"github.com/compose-spec/compose-go/v2/types"
	"github.com/sirupsen/logrus"
)

func newTestService() *Service {
	return &Service{log: logrus.New()}
}

func TestFirstStrayBindSource(t *testing.T) {
	containerStacksDir := "/app/data/stacks"
	tests := []struct {
		name    string
		project *types.Project
		want    string
	}{
		{
			name:    "no services",
			project: &types.Project{Services: types.Services{}},
			want:    "",
		},
		{
			name: "only rewritten bind mounts (host paths)",
			project: &types.Project{Services: types.Services{
				"web": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeBind, Source: "/opt/dockmon/data/stacks/myproj/data"},
				}},
			}},
			want: "",
		},
		{
			name: "stray container-internal bind source",
			project: &types.Project{Services: types.Services{
				"web": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeBind, Source: "/app/data/stacks/myproj/data"},
				}},
			}},
			want: "/app/data/stacks/myproj/data",
		},
		{
			name: "user-provided absolute path outside stacks tree is allowed",
			project: &types.Project{Services: types.Services{
				"web": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeBind, Source: "/etc/ssl/certs"},
				}},
			}},
			want: "",
		},
		{
			name: "named volumes ignored",
			project: &types.Project{Services: types.Services{
				"db": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeVolume, Source: "pgdata"},
				}},
			}},
			want: "",
		},
		{
			name: "sibling path under /app/data not flagged (not under /app/data/stacks)",
			project: &types.Project{Services: types.Services{
				"web": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeBind, Source: "/app/data-other/something"},
				}},
			}},
			want: "",
		},
		{
			name: "non-absolute bind source flagged (compose-go resolution failure)",
			project: &types.Project{Services: types.Services{
				"web": types.ServiceConfig{Volumes: []types.ServiceVolumeConfig{
					{Type: types.VolumeTypeBind, Source: "./data"},
				}},
			}},
			want: "./data",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := firstStrayBindSource(tc.project, containerStacksDir)
			if got != tc.want {
				t.Errorf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestRewriteBindMountPaths(t *testing.T) {
	tests := []struct {
		name             string
		svcName          string
		volType          string
		sourceIn         string
		target           string
		containerWorkDir string
		hostWorkDir      string
		wantSource       string
	}{
		{
			name:             "relative path rewritten",
			svcName:          "web",
			volType:          types.VolumeTypeBind,
			sourceIn:         "/app/data/stacks/mystack/data",
			target:           "/data",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/mnt/host/stacks/mystack",
			wantSource:       "/mnt/host/stacks/mystack/data",
		},
		{
			name:             "absolute path unchanged",
			svcName:          "web",
			volType:          types.VolumeTypeBind,
			sourceIn:         "/host/custom/path",
			target:           "/data",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/mnt/host/stacks/mystack",
			wantSource:       "/host/custom/path",
		},
		{
			name:             "named volume unchanged",
			svcName:          "db",
			volType:          types.VolumeTypeVolume,
			sourceIn:         "pgdata",
			target:           "/var/lib/postgresql/data",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/mnt/host/stacks/mystack",
			wantSource:       "pgdata",
		},
		{
			name:             "sibling path rewritten",
			svcName:          "web",
			volType:          types.VolumeTypeBind,
			sourceIn:         "/app/data/stacks/sibling/shared",
			target:           "/shared",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/mnt/host/stacks/mystack",
			wantSource:       "/mnt/host/stacks/sibling/shared",
		},
		{
			name:             "exact stacks dir not rewritten",
			svcName:          "web",
			volType:          types.VolumeTypeBind,
			sourceIn:         "/app/data/stacks",
			target:           "/stacks",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/mnt/host/stacks/mystack",
			wantSource:       "/app/data/stacks",
		},
		{
			name:             "same paths no-op",
			svcName:          "web",
			volType:          types.VolumeTypeBind,
			sourceIn:         "/app/data/stacks/mystack/data",
			target:           "/data",
			containerWorkDir: "/app/data/stacks/mystack",
			hostWorkDir:      "/app/data/stacks/mystack",
			wantSource:       "/app/data/stacks/mystack/data",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := newTestService()
			project := &types.Project{
				Services: types.Services{
					tt.svcName: {
						Name: tt.svcName,
						Volumes: []types.ServiceVolumeConfig{
							{
								Type:   tt.volType,
								Source: tt.sourceIn,
								Target: tt.target,
							},
						},
					},
				},
			}

			svc.rewriteBindMountPaths(project, tt.containerWorkDir, tt.hostWorkDir)

			got := project.Services[tt.svcName].Volumes[0].Source
			if got != tt.wantSource {
				t.Errorf("Source = %q, want %q", got, tt.wantSource)
			}
		})
	}
}

func TestRewriteBindMountPaths_MultipleServicesAndVolumes(t *testing.T) {
	svc := newTestService()
	project := &types.Project{
		Services: types.Services{
			"web": {
				Name: "web",
				Volumes: []types.ServiceVolumeConfig{
					{
						Type:   types.VolumeTypeBind,
						Source: "/app/data/stacks/mystack/config",
						Target: "/config",
					},
					{
						Type:   types.VolumeTypeVolume,
						Source: "cache",
						Target: "/cache",
					},
				},
			},
			"worker": {
				Name: "worker",
				Volumes: []types.ServiceVolumeConfig{
					{
						Type:   types.VolumeTypeBind,
						Source: "/app/data/stacks/mystack/data",
						Target: "/data",
					},
					{
						Type:   types.VolumeTypeBind,
						Source: "/host/logs",
						Target: "/logs",
					},
				},
			},
		},
	}

	svc.rewriteBindMountPaths(project, "/app/data/stacks/mystack", "/mnt/host/stacks/mystack")

	assertions := []struct {
		svcName string
		volIdx  int
		want    string
	}{
		{"web", 0, "/mnt/host/stacks/mystack/config"},
		{"web", 1, "cache"},
		{"worker", 0, "/mnt/host/stacks/mystack/data"},
		{"worker", 1, "/host/logs"},
	}

	for _, tt := range assertions {
		got := project.Services[tt.svcName].Volumes[tt.volIdx].Source
		if got != tt.want {
			t.Errorf("Services[%s].Volumes[%d].Source = %q, want %q",
				tt.svcName, tt.volIdx, got, tt.want)
		}
	}
}

func TestRewriteBindMountPaths_EmptyServices(t *testing.T) {
	svc := newTestService()
	project := &types.Project{
		Services: types.Services{},
	}

	svc.rewriteBindMountPaths(project, "/app/data/stacks/mystack", "/mnt/host/stacks/mystack")

	if len(project.Services) != 0 {
		t.Errorf("Services length = %d, want 0", len(project.Services))
	}
}

func TestRewriteBindMountPaths_TmpfsUnchanged(t *testing.T) {
	svc := newTestService()
	project := &types.Project{
		Services: types.Services{
			"web": {
				Name: "web",
				Volumes: []types.ServiceVolumeConfig{
					{
						Type:   types.VolumeTypeTmpfs,
						Target: "/tmp",
					},
				},
			},
		},
	}

	svc.rewriteBindMountPaths(project, "/app/data/stacks/mystack", "/mnt/host/stacks/mystack")

	got := project.Services["web"].Volumes[0].Type
	if got != types.VolumeTypeTmpfs {
		t.Errorf("Type = %q, want %q", got, types.VolumeTypeTmpfs)
	}
	if project.Services["web"].Volumes[0].Source != "" {
		t.Errorf("Source = %q, want empty", project.Services["web"].Volumes[0].Source)
	}
}
