package main

import (
	"bufio"
	"errors"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// HostProcReader reads actual host CPU/memory stats from /host/proc
// when mounted as /proc:/host/proc:ro in the container
type HostProcReader struct {
	procPath    string
	available   bool
	mu          sync.RWMutex
	lastCPU     cpuTimes
	lastCPUTime time.Time
}

// cpuTimes holds CPU time values from /proc/stat
type cpuTimes struct {
	user    uint64
	nice    uint64
	system  uint64
	idle    uint64
	iowait  uint64
	irq     uint64
	softirq uint64
	steal   uint64
}

// total returns total CPU time
func (c cpuTimes) total() uint64 {
	return c.user + c.nice + c.system + c.idle + c.iowait + c.irq + c.softirq + c.steal
}

// idle returns idle CPU time (idle + iowait)
func (c cpuTimes) idleTime() uint64 {
	return c.idle + c.iowait
}

// HostProcStats contains the actual host statistics
type HostProcStats struct {
	CPUPercent       float64
	MemoryUsedBytes  uint64
	MemoryTotalBytes uint64
	MemoryPercent    float64
}

// NewHostProcReader creates a new reader, checking if /host/proc is available
func NewHostProcReader() *HostProcReader {
	procPath := "/host/proc"

	// Check if /host/proc/stat exists
	_, err := os.Stat(procPath + "/stat")
	available := err == nil

	return &HostProcReader{
		procPath:  procPath,
		available: available,
	}
}

// IsAvailable returns true if /host/proc is mounted and readable
func (h *HostProcReader) IsAvailable() bool {
	return h.available
}

// GetStats reads current CPU and memory stats from /host/proc
func (h *HostProcReader) GetStats() (*HostProcStats, error) {
	if !h.available {
		return nil, nil
	}

	cpuPercent, err := h.getCPUPercent()
	if err != nil {
		return nil, err
	}

	memUsed, memTotal, memPercent, err := h.getMemoryStats()
	if err != nil {
		return nil, err
	}

	return &HostProcStats{
		CPUPercent:       cpuPercent,
		MemoryUsedBytes:  memUsed,
		MemoryTotalBytes: memTotal,
		MemoryPercent:    memPercent,
	}, nil
}

// getCPUPercent calculates CPU usage percentage from /proc/stat
func (h *HostProcReader) getCPUPercent() (float64, error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	currentCPU, err := h.readCPUTimes()
	if err != nil {
		return 0, err
	}

	now := time.Now()

	// Need at least 2 samples to calculate percentage
	if h.lastCPUTime.IsZero() {
		h.lastCPU = currentCPU
		h.lastCPUTime = now
		return 0, nil
	}

	// Calculate delta
	totalDelta := currentCPU.total() - h.lastCPU.total()
	idleDelta := currentCPU.idleTime() - h.lastCPU.idleTime()

	// Update last sample
	h.lastCPU = currentCPU
	h.lastCPUTime = now

	if totalDelta == 0 {
		return 0, nil
	}

	// CPU usage = (1 - idle/total) * 100
	cpuPercent := (1.0 - float64(idleDelta)/float64(totalDelta)) * 100.0

	// Clamp to valid range
	if cpuPercent < 0 {
		cpuPercent = 0
	}
	if cpuPercent > 100 {
		cpuPercent = 100
	}

	return cpuPercent, nil
}

// readCPUTimes reads CPU times from /proc/stat
func (h *HostProcReader) readCPUTimes() (cpuTimes, error) {
	file, err := os.Open(h.procPath + "/stat")
	if err != nil {
		return cpuTimes{}, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "cpu ") {
			fields := strings.Fields(line)
			if len(fields) < 8 {
				return cpuTimes{}, errors.New("invalid cpu line in /proc/stat: insufficient fields")
			}

			var ct cpuTimes
			var parseErr error

			ct.user, parseErr = strconv.ParseUint(fields[1], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu user value %q: %v", fields[1], parseErr)
			}
			ct.nice, parseErr = strconv.ParseUint(fields[2], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu nice value %q: %v", fields[2], parseErr)
			}
			ct.system, parseErr = strconv.ParseUint(fields[3], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu system value %q: %v", fields[3], parseErr)
			}
			ct.idle, parseErr = strconv.ParseUint(fields[4], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu idle value %q: %v", fields[4], parseErr)
			}
			ct.iowait, parseErr = strconv.ParseUint(fields[5], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu iowait value %q: %v", fields[5], parseErr)
			}
			ct.irq, parseErr = strconv.ParseUint(fields[6], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu irq value %q: %v", fields[6], parseErr)
			}
			ct.softirq, parseErr = strconv.ParseUint(fields[7], 10, 64)
			if parseErr != nil {
				log.Printf("Warning: failed to parse cpu softirq value %q: %v", fields[7], parseErr)
			}
			if len(fields) > 8 {
				ct.steal, parseErr = strconv.ParseUint(fields[8], 10, 64)
				if parseErr != nil {
					log.Printf("Warning: failed to parse cpu steal value %q: %v", fields[8], parseErr)
				}
			}

			return ct, nil
		}
	}

	if err := scanner.Err(); err != nil {
		return cpuTimes{}, err
	}

	return cpuTimes{}, errors.New("cpu stats line not found in /proc/stat")
}

// getMemoryStats reads memory stats from /proc/meminfo
func (h *HostProcReader) getMemoryStats() (used, total uint64, percent float64, err error) {
	file, err := os.Open(h.procPath + "/meminfo")
	if err != nil {
		return 0, 0, 0, err
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

		// Values are in kB
		value, parseErr := strconv.ParseUint(fields[1], 10, 64)
		if parseErr != nil {
			log.Printf("Warning: failed to parse meminfo value %q: %v", fields[1], parseErr)
			continue
		}
		value *= 1024 // Convert to bytes

		switch fields[0] {
		case "MemTotal:":
			memTotal = value
		case "MemAvailable:":
			memAvailable = value
		}

		// We have both values we need
		if memTotal > 0 && memAvailable > 0 {
			break
		}
	}

	if err := scanner.Err(); err != nil {
		return 0, 0, 0, err
	}

	// Used memory = Total - Available
	// This matches the agent's calculation and is the kernel-recommended approach
	// MemAvailable accounts for page cache and reclaimable slabs correctly
	var memUsed uint64
	if memAvailable > memTotal {
		// Underflow protection - shouldn't happen but be defensive
		memUsed = 0
	} else {
		memUsed = memTotal - memAvailable
	}

	if memTotal > 0 {
		percent = (float64(memUsed) / float64(memTotal)) * 100.0
	}

	return memUsed, memTotal, percent, nil
}
