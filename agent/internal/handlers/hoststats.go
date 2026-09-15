package handlers

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-shared/hostdisk"
	"github.com/sirupsen/logrus"
)

// /proc/meminfo reports kilobytes.
const bytesPerKB = 1024

// errCPUBaseline marks the first /proc/stat read, which has no previous
// counters to diff against and therefore no usable percentage.
var errCPUBaseline = errors.New("first CPU reading is a baseline")

// DiskReader supplies the host filesystem reading for the host sample.
// *hostdisk.Reader satisfies it; nil disables disk reporting.
type DiskReader interface {
	Read(ctx context.Context) (*hostdisk.Reading, error)
}

// HostStatsHandler collects host-level metrics from /proc (or /host/proc in container mode)
type HostStatsHandler struct {
	log      *logrus.Logger
	sendJSON func(payload interface{}) error
	disk     DiskReader

	// Paths to proc and sys filesystems (auto-detected)
	procPath string // /proc or /host/proc
	sysPath  string // /sys or /host/sys

	// Previous values for calculating deltas
	prevCPU  cpuStats
	prevNet  map[string]netStats
	prevTime time.Time
	mu       sync.Mutex

	// Host samples reach the alert evaluator only through this dual-send —
	// the control WebSocket feeds the UI ring buffer alone.
	statsSink
}

// memReading is a single /proc/meminfo sample.
type memReading struct {
	percent    float64
	usedBytes  uint64
	totalBytes uint64
}

type cpuStats struct {
	user    uint64
	nice    uint64
	system  uint64
	idle    uint64
	iowait  uint64
	irq     uint64
	softirq uint64
	steal   uint64
}

type netStats struct {
	rxBytes uint64
	txBytes uint64
}

// NewHostStatsHandler creates a new host stats handler
// Auto-detects /host/proc (container mode) vs /proc (systemd mode)
func NewHostStatsHandler(log *logrus.Logger, sendJSON func(interface{}) error, disk DiskReader) *HostStatsHandler {
	procPath := "/proc"
	sysPath := "/sys"

	// Check if /host/proc is available (container mode with host proc mounted)
	if _, err := os.Stat("/host/proc/stat"); err == nil {
		procPath = "/host/proc"
		log.Info("Using /host/proc for host stats (container mode with mount)")
	}

	// Check if /host/sys is available (container mode with host sys mounted)
	if _, err := os.Stat("/host/sys/class/net"); err == nil {
		sysPath = "/host/sys"
		log.Info("Using /host/sys for network stats (container mode with mount)")
	}

	return &HostStatsHandler{
		log:      log,
		sendJSON: sendJSON,
		disk:     disk,
		procPath: procPath,
		sysPath:  sysPath,
		prevNet:  make(map[string]netStats),
	}
}

// StartCollection starts periodic host stats collection
func (h *HostStatsHandler) StartCollection(ctx context.Context, interval time.Duration) {
	h.log.Infof("Starting host stats collection every %v", interval)

	// Initial collection to set baseline
	h.collect(ctx)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			h.log.Info("Stopping host stats collection")
			return
		case <-ticker.C:
			h.collect(ctx)
		}
	}
}

func (h *HostStatsHandler) collect(ctx context.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()

	now := time.Now()

	// Read everything first so the deltas stay seeded even on a pass we do
	// not publish.
	cpuPercent, cpuErr := h.readCPUPercent()
	mem, memErr := h.readMemory()
	netBytesPerSec := h.calculateNetBytesPerSec(now)
	h.prevTime = now

	// A failed /proc read must not publish a sample: zeros are
	// indistinguishable from a healthy idle host, on both the UI wire and
	// the alert wire. The same goes for the first CPU read, which only seeds
	// the counters — publishing its 0% could clear a live host CPU alert.
	if cpuErr != nil {
		if errors.Is(cpuErr, errCPUBaseline) {
			h.log.Debug("Skipping first host stats sample (CPU baseline)")
		} else {
			h.log.Errorf("Skipping host stats sample: %v", cpuErr)
		}
		return
	}
	if memErr != nil {
		h.log.Errorf("Skipping host stats sample: %v", memErr)
		return
	}

	// Send to backend (format expected by _handle_system_stats)
	msg := map[string]interface{}{
		"type": "stats",
		"stats": map[string]interface{}{
			"cpu_percent":       cpuPercent,
			"mem_percent":       mem.percent,
			"net_bytes_per_sec": netBytesPerSec,
		},
	}

	if err := h.sendJSON(msg); err != nil {
		h.log.Errorf("Failed to send host stats: %v", err)
	} else {
		h.log.Debugf("Sent host stats: CPU=%.1f%%, MEM=%.1f%%, NET=%.0f B/s", cpuPercent, mem.percent, netBytesPerSec)
	}

	if ss := h.sender(); ss != nil {
		ss.Send(statsmsg.AgentStatsMsg{
			Type:             statsmsg.TypeHostStats,
			CPUPercent:       cpuPercent,
			MemoryPercent:    mem.percent,
			MemoryUsedBytes:  mem.usedBytes,
			MemoryLimitBytes: mem.totalBytes,
			Timestamp:        now.UTC().Format(time.RFC3339),
			HostDisk:         h.readDisk(ctx),
		})
	}
}

// readDisk returns the host disk fields for the sample, or nil when they
// cannot be measured. Unlike a /proc failure, a disk failure must not skip the
// sample: that would silence host CPU and memory alerting to add disk.
func (h *HostStatsHandler) readDisk(ctx context.Context) *hostdisk.HostDisk {
	if h.disk == nil {
		return nil
	}
	r, err := h.disk.Read(ctx)
	if err != nil {
		return nil
	}
	return r.Wire()
}

// readCPUPercent reads /proc/stat (or /host/proc/stat) and calculates CPU usage percentage
func (h *HostStatsHandler) readCPUPercent() (float64, error) {
	statPath := filepath.Join(h.procPath, "stat")
	file, err := os.Open(statPath)
	if err != nil {
		return 0, fmt.Errorf("failed to open %s: %w", statPath, err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "cpu ") {
			fields := strings.Fields(line)
			if len(fields) < 8 {
				continue
			}

			curr := cpuStats{
				user:    parseUint(fields[1]),
				nice:    parseUint(fields[2]),
				system:  parseUint(fields[3]),
				idle:    parseUint(fields[4]),
				iowait:  parseUint(fields[5]),
				irq:     parseUint(fields[6]),
				softirq: parseUint(fields[7]),
			}
			if len(fields) > 8 {
				curr.steal = parseUint(fields[8])
			}

			// Calculate deltas
			if h.prevCPU.idle == 0 && h.prevCPU.user == 0 {
				h.prevCPU = curr
				return 0, errCPUBaseline
			}

			prevTotal := h.prevCPU.user + h.prevCPU.nice + h.prevCPU.system + h.prevCPU.idle +
				h.prevCPU.iowait + h.prevCPU.irq + h.prevCPU.softirq + h.prevCPU.steal
			currTotal := curr.user + curr.nice + curr.system + curr.idle +
				curr.iowait + curr.irq + curr.softirq + curr.steal

			prevIdle := h.prevCPU.idle + h.prevCPU.iowait
			currIdle := curr.idle + curr.iowait

			totalDelta := currTotal - prevTotal
			idleDelta := currIdle - prevIdle

			h.prevCPU = curr

			if totalDelta == 0 {
				return 0, nil
			}

			cpuPercent := float64(totalDelta-idleDelta) / float64(totalDelta) * 100
			return cpuPercent, nil
		}
	}

	return 0, fmt.Errorf("no aggregate cpu line in %s", statPath)
}

// readMemory reads /proc/meminfo (or /host/proc/meminfo). Values there are in
// kB, so they are scaled to bytes.
func (h *HostStatsHandler) readMemory() (memReading, error) {
	meminfoPath := filepath.Join(h.procPath, "meminfo")
	file, err := os.Open(meminfoPath)
	if err != nil {
		return memReading{}, fmt.Errorf("failed to open %s: %w", meminfoPath, err)
	}
	defer file.Close()

	var memTotal, memAvailable uint64

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}

		value := parseUint(fields[1])

		switch fields[0] {
		case "MemTotal:":
			memTotal = value
		case "MemAvailable:":
			memAvailable = value
		}

		// We have both values, can calculate
		if memTotal > 0 && memAvailable > 0 {
			break
		}
	}

	if memTotal == 0 {
		return memReading{}, fmt.Errorf("no MemTotal in %s", meminfoPath)
	}

	// Underflow protection - shouldn't happen but be defensive
	var memUsed uint64
	if memAvailable > memTotal {
		memUsed = 0
	} else {
		memUsed = memTotal - memAvailable
	}

	return memReading{
		percent:    float64(memUsed) / float64(memTotal) * 100,
		usedBytes:  memUsed * bytesPerKB,
		totalBytes: memTotal * bytesPerKB,
	}, nil
}

// calculateNetBytesPerSec reads /sys/class/net/*/statistics and calculates total bytes/sec
func (h *HostStatsHandler) calculateNetBytesPerSec(now time.Time) float64 {
	if h.prevTime.IsZero() {
		// First reading, just store values
		h.readNetStats()
		return 0
	}

	elapsed := now.Sub(h.prevTime).Seconds()
	if elapsed <= 0 {
		return 0
	}

	// Read current stats
	currNet := h.readNetStats()

	var totalBytesPerSec float64

	for iface, curr := range currNet {
		if prev, ok := h.prevNet[iface]; ok {
			// Skip interfaces whose counters went backwards (reset/renumber) to
			// avoid uint64 underflow producing a bogus huge rate.
			if curr.rxBytes < prev.rxBytes || curr.txBytes < prev.txBytes {
				continue
			}
			rxDelta := curr.rxBytes - prev.rxBytes
			txDelta := curr.txBytes - prev.txBytes
			totalBytesPerSec += float64(rxDelta+txDelta) / elapsed
		}
	}

	h.prevNet = currNet
	return totalBytesPerSec
}

func (h *HostStatsHandler) readNetStats() map[string]netStats {
	result := make(map[string]netStats)

	netPath := filepath.Join(h.sysPath, "class", "net")
	entries, err := os.ReadDir(netPath)
	if err != nil {
		h.log.Errorf("Failed to read %s: %v", netPath, err)
		return result
	}

	for _, entry := range entries {
		iface := entry.Name()

		// Skip virtual and container-related interfaces
		// We want to count physical NICs, bonds, and VLANs but not Docker/container interfaces
		if h.isVirtualInterface(iface) {
			continue
		}

		// Only count interfaces that are up (operstate == "up" or "unknown")
		// "unknown" is used by some drivers for interfaces that are up but don't report state
		if !h.isInterfaceUp(iface) {
			continue
		}

		rxBytes := h.readNetStat(iface, "rx_bytes")
		txBytes := h.readNetStat(iface, "tx_bytes")

		result[iface] = netStats{
			rxBytes: rxBytes,
			txBytes: txBytes,
		}
	}

	return result
}

// isVirtualInterface returns true if the interface is a virtual/container interface
func (h *HostStatsHandler) isVirtualInterface(iface string) bool {
	// Skip loopback
	if iface == "lo" {
		return true
	}

	// Skip Docker/container virtual interfaces
	virtualPrefixes := []string{
		"veth",    // Docker veth pairs
		"br-",     // Docker bridge networks
		"docker",  // Docker default bridge
		"virbr",   // libvirt bridges
		"vnet",    // libvirt/KVM vnet interfaces
		"tun",     // VPN tunnels
		"tap",     // TAP devices
		"dummy",   // Dummy interfaces
		"gre",     // GRE tunnels
		"sit",     // IPv6-in-IPv4 tunnels
		"ip6tnl",  // IPv6 tunnels
		"vxlan",   // VXLAN interfaces
		"flannel", // Kubernetes flannel
		"cni",     // Kubernetes CNI
		"cali",    // Calico interfaces
		"weave",   // Weave interfaces
	}

	for _, prefix := range virtualPrefixes {
		if strings.HasPrefix(iface, prefix) {
			return true
		}
	}

	return false
}

// isInterfaceUp checks if the interface operstate is "up" or "unknown"
func (h *HostStatsHandler) isInterfaceUp(iface string) bool {
	operstateFile := filepath.Join(h.sysPath, "class", "net", iface, "operstate")
	data, err := os.ReadFile(operstateFile)
	if err != nil {
		// If we can't read operstate, assume it's up (conservative)
		return true
	}

	state := strings.TrimSpace(string(data))
	// "up" = interface is up, "unknown" = driver doesn't report state (treat as up)
	return state == "up" || state == "unknown"
}

func (h *HostStatsHandler) readNetStat(iface, stat string) uint64 {
	path := filepath.Join(h.sysPath, "class", "net", iface, "statistics", stat)
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	return parseUint(strings.TrimSpace(string(data)))
}

func parseUint(s string) uint64 {
	v, _ := strconv.ParseUint(s, 10, 64)
	return v
}
