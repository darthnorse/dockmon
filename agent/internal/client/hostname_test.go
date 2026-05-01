package client

import "testing"

func TestSelectHostname(t *testing.T) {
	tests := []struct {
		name           string
		agentName      string
		systemHostname string
		osHostname     string
		engineID       string
		want           string
		wantSource     string
	}{
		{
			name:           "agent name wins over everything",
			agentName:      "prod-web-01",
			systemHostname: "ubuntu-server",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "prod-web-01",
			wantSource:     "agent_name",
		},
		{
			name:           "system hostname used when agent name empty",
			agentName:      "",
			systemHostname: "ubuntu-server",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "ubuntu-server",
			wantSource:     "daemon",
		},
		{
			name:           "os hostname used when agent name and system hostname empty",
			agentName:      "",
			systemHostname: "",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "container-abc",
			wantSource:     "os",
		},
		{
			name:           "truncated engine id used when nothing else",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abcdef1234567890",
			want:           "abcdef123456",
			wantSource:     "engine_id",
		},
		{
			name:           "engine id exactly 12 chars returned as-is",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abcdef123456",
			want:           "abcdef123456",
			wantSource:     "engine_id",
		},
		{
			name:           "short engine id returned as-is",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abc123",
			want:           "abc123",
			wantSource:     "engine_id",
		},
		{
			name:           "all empty returns empty string and engine_id source",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "",
			want:           "",
			wantSource:     "engine_id",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, gotSource := selectHostname(tt.agentName, tt.systemHostname, tt.osHostname, tt.engineID)
			if got != tt.want {
				t.Errorf("selectHostname(%q, %q, %q, %q) hostname = %q, want %q",
					tt.agentName, tt.systemHostname, tt.osHostname, tt.engineID, got, tt.want)
			}
			if gotSource != tt.wantSource {
				t.Errorf("selectHostname(%q, %q, %q, %q) source = %q, want %q",
					tt.agentName, tt.systemHostname, tt.osHostname, tt.engineID, gotSource, tt.wantSource)
			}
		})
	}
}
