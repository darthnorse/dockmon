package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/dockmon/compose-service/internal/server"
	"github.com/sirupsen/logrus"
)

func main() {
	// Initialize logger
	log := logrus.New()
	log.SetOutput(os.Stdout)
	log.SetFormatter(&logrus.JSONFormatter{
		TimestampFormat: time.RFC3339,
	})

	// Log level from environment
	level := os.Getenv("LOG_LEVEL")
	if level == "" {
		level = "info"
	}
	logLevel, err := logrus.ParseLevel(level)
	if err != nil {
		logLevel = logrus.InfoLevel
	}
	log.SetLevel(logLevel)

	// Socket path from environment or default
	socketPath := os.Getenv("COMPOSE_SOCKET_PATH")
	if socketPath == "" {
		socketPath = "/tmp/compose.sock"
	}

	log.WithFields(logrus.Fields{
		"socket":    socketPath,
		"log_level": logLevel.String(),
	}).Info("Compose service starting")

	// Create server
	srv := server.NewServer(socketPath, log)

	// Context with cancellation for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigCh
		log.WithField("signal", sig.String()).Info("Received signal, shutting down...")
		cancel()
	}()

	// Start server
	if err := srv.Start(ctx); err != nil {
		log.WithError(err).Fatal("Server failed")
	}

	log.Info("Compose service stopped")
}
