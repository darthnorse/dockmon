package main

import (
	"testing"
	"time"
)

// Two samples one second apart must yield per-direction rates as well as the total.
func TestUpdateContainerStats_PerDirectionRates(t *testing.T) {
	c := NewStatsCache()
	first := &ContainerStats{ContainerID: "aaa111111111", HostID: "h1", NetworkRx: 1000, NetworkTx: 500}
	c.UpdateContainerStats(first)

	c.mu.Lock()
	c.lastNetStats["h1:aaa111111111"].timestamp = time.Now().Add(-time.Second)
	c.mu.Unlock()

	second := &ContainerStats{ContainerID: "aaa111111111", HostID: "h1", NetworkRx: 3000, NetworkTx: 1500}
	c.UpdateContainerStats(second)

	if second.NetBytesPerSec < 2900 || second.NetBytesPerSec > 3100 {
		t.Fatalf("total rate = %v, want ~3000", second.NetBytesPerSec)
	}
	if second.NetRxBytesPerSec < 1900 || second.NetRxBytesPerSec > 2100 {
		t.Fatalf("rx rate = %v, want ~2000", second.NetRxBytesPerSec)
	}
	if second.NetTxBytesPerSec < 900 || second.NetTxBytesPerSec > 1100 {
		t.Fatalf("tx rate = %v, want ~1000", second.NetTxBytesPerSec)
	}
}

// A counter reset (container restart) zeroes every rate, not just the total.
func TestUpdateContainerStats_ResetZeroesPerDirectionRates(t *testing.T) {
	c := NewStatsCache()
	c.UpdateContainerStats(&ContainerStats{ContainerID: "aaa111111111", HostID: "h1", NetworkRx: 5000, NetworkTx: 5000})
	c.mu.Lock()
	c.lastNetStats["h1:aaa111111111"].timestamp = time.Now().Add(-time.Second)
	c.mu.Unlock()

	after := &ContainerStats{ContainerID: "aaa111111111", HostID: "h1", NetworkRx: 10, NetworkTx: 10}
	c.UpdateContainerStats(after)

	if after.NetBytesPerSec != 0 || after.NetRxBytesPerSec != 0 || after.NetTxBytesPerSec != 0 {
		t.Fatalf("rates after reset = %v/%v/%v, want 0", after.NetBytesPerSec, after.NetRxBytesPerSec, after.NetTxBytesPerSec)
	}
}
