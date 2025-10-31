package main

import (
	"context"
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
	version = "2.2.0"
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
	myContainerID, err := dockerClient.GetMyContainerID(ctx)
	if err != nil {
		log.WithError(err).Warn("Could not determine agent container ID (self-update disabled)")
	} else {
		log.WithField("container_id", myContainerID).Info("Detected agent container ID")
	}

	// Initialize WebSocket client
	wsClient := client.NewWebSocketClient(cfg, dockerClient, engineID, myContainerID, log)

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

	// Set format
	if cfg.LogJSON {
		log.SetFormatter(&logrus.JSONFormatter{
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
