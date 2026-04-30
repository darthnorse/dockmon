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
	}{
		{
			name:           "agent name wins over everything",
			agentName:      "prod-web-01",
			systemHostname: "ubuntu-server",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "prod-web-01",
		},
		{
			name:           "system hostname used when agent name empty",
			agentName:      "",
			systemHostname: "ubuntu-server",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "ubuntu-server",
		},
		{
			name:           "os hostname used when agent name and system hostname empty",
			agentName:      "",
			systemHostname: "",
			osHostname:     "container-abc",
			engineID:       "abcdef1234567890",
			want:           "container-abc",
		},
		{
			name:           "truncated engine id used when nothing else",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abcdef1234567890",
			want:           "abcdef123456",
		},
		{
			name:           "engine id exactly 12 chars returned as-is",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abcdef123456",
			want:           "abcdef123456",
		},
		{
			name:           "short engine id returned as-is",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "abc123",
			want:           "abc123",
		},
		{
			name:           "all empty returns empty string",
			agentName:      "",
			systemHostname: "",
			osHostname:     "",
			engineID:       "",
			want:           "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := selectHostname(tt.agentName, tt.systemHostname, tt.osHostname, tt.engineID)
			if got != tt.want {
				t.Errorf("selectHostname(%q, %q, %q, %q) = %q, want %q",
					tt.agentName, tt.systemHostname, tt.osHostname, tt.engineID, got, tt.want)
			}
		})
	}
}
