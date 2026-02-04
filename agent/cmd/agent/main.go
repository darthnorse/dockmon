package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/darthnorse/dockmon-agent/internal/client"
	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/sirupsen/logrus"
)

var (
	version = "1.0.4"
	commit  = "dev"
)

func main() {
	// Load configuration
	cfg, err := config.LoadFromEnv()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load configuration: %v\n", err)
		os.Exit(1)
	}

	// Set agent version from build
	cfg.AgentVersion = version

	// Setup logging
	log := setupLogging(cfg)
	log.WithFields(logrus.Fields{
		"version": version,
		"commit":  commit,
	}).Info("DockMon Agent starting")

	// Create context that cancels on signal
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	defer func() {
		signal.Stop(sigChan)
		close(sigChan)
	}()

	// Initialize Docker client
	dockerClient, err := docker.NewClient(cfg, log)
	if err != nil {
		log.WithError(err).Fatal("Failed to create Docker client")
	}
	defer dockerClient.Close()

	// Get Docker engine ID
	engineID, err := dockerClient.GetEngineID(ctx)
	if err != nil {
		log.WithError(err).Fatal("Failed to get Docker engine ID")
	}

	log.WithField("engine_id", engineID).Info("Connected to Docker daemon")

	// Get agent's own container ID (for self-update)
	// Try cgroup detection first, then fall back to HOSTNAME environment variable
	myContainerID, err := dockerClient.GetMyContainerID(ctx)
	if err != nil {
		log.WithError(err).Debug("Could not detect container ID from cgroup")
		// Fallback: Docker sets HOSTNAME to container ID by default
		if hostname := os.Getenv("HOSTNAME"); hostname != "" && len(hostname) >= 12 {
			// Verify it looks like a container ID (hex string)
			isHex := true
			for _, c := range hostname[:12] {
				if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
					isHex = false
					break
				}
			}
			if isHex {
				myContainerID = hostname[:12]
				log.WithField("container_id", myContainerID).Info("Using HOSTNAME as container ID")
			}
		}
		if myContainerID == "" {
			log.Warn("Could not determine agent container ID (container self-update disabled)")
		}
	} else {
		myContainerID = myContainerID[:12] // Normalize to short ID
		log.WithField("container_id", myContainerID).Info("Detected agent container ID from cgroup")
	}

	// Initialize WebSocket client
	wsClient, err := client.NewWebSocketClient(ctx, cfg, dockerClient, engineID, myContainerID, log)
	if err != nil {
		log.WithError(err).Fatal("Failed to create WebSocket client")
	}

	// Check for pending self-update on startup
	if err := wsClient.CheckPendingUpdate(); err != nil {
		log.WithError(err).Warn("Failed to check/apply pending update")
	}

	// Start client in background
	go func() {
		if err := wsClient.Run(ctx); err != nil {
			log.WithError(err).Error("WebSocket client stopped with error")
			cancel()
		}
	}()

	// Wait for shutdown signal
	select {
	case sig := <-sigChan:
		log.WithField("signal", sig).Info("Received shutdown signal")
	case <-ctx.Done():
		log.Info("Context cancelled")
	}

	log.Info("Shutting down gracefully...")
	cancel()

	// Wait a moment for graceful shutdown
	// (WebSocket client will close connection properly)
	// TODO: Add proper shutdown coordination
}

// setupLogging configures the logger based on config
func setupLogging(cfg *config.Config) *logrus.Logger {
	log := logrus.New()

	// Set log level
	level, err := logrus.ParseLevel(cfg.LogLevel)
	if err != nil {
		level = logrus.InfoLevel
	}
	log.SetLevel(level)

	// Set format - always use timestamp-first format for readability
	if cfg.LogJSON {
		log.SetFormatter(&TimestampFirstJSONFormatter{
			TimestampFormat: "2006-01-02T15:04:05.000Z07:00",
		})
	} else {
		log.SetFormatter(&logrus.TextFormatter{
			FullTimestamp:   true,
			TimestampFormat: "2006-01-02 15:04:05",
		})
	}

	return log
}

// TimestampFirstJSONFormatter outputs JSON with timestamp as the first field
type TimestampFirstJSONFormatter struct {
	TimestampFormat string
}

// Format renders a log entry as JSON with timestamp first
func (f *TimestampFirstJSONFormatter) Format(entry *logrus.Entry) ([]byte, error) {
	// Build ordered output: time, level, msg, then other fields alphabetically
	var b bytes.Buffer
	b.WriteString(`{"time":"`)

	timestampFormat := f.TimestampFormat
	if timestampFormat == "" {
		timestampFormat = "2006-01-02T15:04:05.000Z07:00"
	}
	b.WriteString(entry.Time.Format(timestampFormat))
	b.WriteString(`","level":"`)
	b.WriteString(entry.Level.String())
	b.WriteString(`","msg":`)

	// JSON encode the message to handle special characters
	msgBytes, _ := json.Marshal(entry.Message)
	b.Write(msgBytes)

	// Add any additional fields
	for key, value := range entry.Data {
		b.WriteString(`,"`)
		b.WriteString(key)
		b.WriteString(`":`)
		valueBytes, err := json.Marshal(value)
		if err != nil {
			valueBytes = []byte(`"` + fmt.Sprintf("%v", value) + `"`)
		}
		b.Write(valueBytes)
	}

	b.WriteString("}\n")
	return b.Bytes(), nil
}
