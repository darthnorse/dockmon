package handlers

import (
	"bufio"
	"context"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/sirupsen/logrus"
)

// HostStatsHandler collects host-level metrics from /proc for systemd agents
type HostStatsHandler struct {
	log      *logrus.Logger
	sendJSON func(payload interface{}) error

	// Previous values for calculating deltas
	prevCPU  cpuStats
	prevNet  map[string]netStats
	prevTime time.Time
	mu       sync.Mutex
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
func NewHostStatsHandler(log *logrus.Logger, sendJSON func(interface{}) error) *HostStatsHandler {
	return &HostStatsHandler{
		log:      log,
		sendJSON: sendJSON,
		prevNet:  make(map[string]netStats),
	}
}

// StartCollection starts periodic host stats collection
func (h *HostStatsHandler) StartCollection(ctx context.Context, interval time.Duration) {
	h.log.Infof("Starting host stats collection every %v", interval)

	// Initial collection to set baseline
	h.collect()

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			h.log.Info("Stopping host stats collection")
			return
		case <-ticker.C:
			h.collect()
		}
	}
}

func (h *HostStatsHandler) collect() {
	h.mu.Lock()
	defer h.mu.Unlock()

	now := time.Now()

	// Calculate CPU percentage
	cpuPercent := h.calculateCPUPercent()

	// Calculate memory percentage
	memPercent := h.calculateMemPercent()

	// Calculate network bytes/sec
	netBytesPerSec := h.calculateNetBytesPerSec(now)

	h.prevTime = now

	// Send to backend (format expected by _handle_system_stats)
	msg := map[string]interface{}{
		"type": "stats",
		"stats": map[string]interface{}{
			"cpu_percent":       cpuPercent,
			"mem_percent":       memPercent,
			"net_bytes_per_sec": netBytesPerSec,
		},
	}

	if err := h.sendJSON(msg); err != nil {
		h.log.Errorf("Failed to send host stats: %v", err)
	} else {
		h.log.Debugf("Sent host stats: CPU=%.1f%%, MEM=%.1f%%, NET=%.0f B/s", cpuPercent, memPercent, netBytesPerSec)
	}
}

// calculateCPUPercent reads /proc/stat and calculates CPU usage percentage
func (h *HostStatsHandler) calculateCPUPercent() float64 {
	file, err := os.Open("/proc/stat")
	if err != nil {
		h.log.Errorf("Failed to open /proc/stat: %v", err)
		return 0
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
				// First reading, store and return 0
				h.prevCPU = curr
				return 0
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
				return 0
			}

			cpuPercent := float64(totalDelta-idleDelta) / float64(totalDelta) * 100
			return cpuPercent
		}
	}

	return 0
}

// calculateMemPercent reads /proc/meminfo and calculates memory usage percentage
func (h *HostStatsHandler) calculateMemPercent() float64 {
	file, err := os.Open("/proc/meminfo")
	if err != nil {
		h.log.Errorf("Failed to open /proc/meminfo: %v", err)
		return 0
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
		return 0
	}

	memUsed := memTotal - memAvailable
	return float64(memUsed) / float64(memTotal) * 100
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

	netPath := "/sys/class/net"
	entries, err := os.ReadDir(netPath)
	if err != nil {
		h.log.Errorf("Failed to read %s: %v", netPath, err)
		return result
	}

	for _, entry := range entries {
		iface := entry.Name()

		// Skip loopback and virtual interfaces
		if iface == "lo" || strings.HasPrefix(iface, "veth") || strings.HasPrefix(iface, "br-") ||
			strings.HasPrefix(iface, "docker") {
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

func (h *HostStatsHandler) readNetStat(iface, stat string) uint64 {
	path := filepath.Join("/sys/class/net", iface, "statistics", stat)
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
