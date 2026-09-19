package statsmsg

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/darthnorse/dockmon-shared/hostdisk"
)

// A plain float64 marshals its zero value, so a host that cannot measure
// disk would report 0% used. Assert on the bytes, not the struct.
func TestAgentStatsMsg_NoDiskReadingProducesNoDiskKeys(t *testing.T) {
	data, err := json.Marshal(AgentStatsMsg{Type: TypeHostStats, CPUPercent: 12.5})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "disk_") {
		t.Errorf("unset disk reading leaked onto the wire: %s", data)
	}
}

func TestAgentStatsMsg_GenuineZeroPercentStaysOnTheWire(t *testing.T) {
	data, err := json.Marshal(AgentStatsMsg{
		Type:     TypeHostStats,
		HostDisk: &hostdisk.HostDisk{DiskPercent: 0, DiskUsedBytes: 0, DiskAvailableBytes: 10, DiskTotalBytes: 10, DiskSource: "/"},
	})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]json.RawMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if string(decoded["disk_percent"]) != "0" {
		t.Errorf("disk_percent=%s, want 0 on the wire", decoded["disk_percent"])
	}
}

// The evaluator and the stats-service read flat keys; the five travel together.
func TestAgentStatsMsg_DiskFieldsAreFlatAndComplete(t *testing.T) {
	data, err := json.Marshal(AgentStatsMsg{
		Type:     TypeHostStats,
		HostDisk: &hostdisk.HostDisk{DiskPercent: 54.7, DiskUsedBytes: 1, DiskAvailableBytes: 2, DiskTotalBytes: 4, DiskSource: "/var/lib/docker"},
	})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]json.RawMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"disk_percent", "disk_used_bytes", "disk_available_bytes", "disk_total_bytes", "disk_source"} {
		if _, ok := decoded[key]; !ok {
			t.Errorf("missing top-level key %q in %s", key, data)
		}
	}
	if _, nested := decoded["disk"]; nested {
		t.Errorf("disk fields are nested, the evaluator reads flat keys: %s", data)
	}
}
