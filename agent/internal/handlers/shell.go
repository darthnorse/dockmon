package handlers

import (
	"context"
	"encoding/base64"
	"io"
	"sync"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-agent/pkg/types"
	dockertypes "github.com/docker/docker/api/types"
	"github.com/sirupsen/logrus"
)

// ShellSession represents an active shell session
type ShellSession struct {
	SessionID   string
	ContainerID string
	ExecID      string
	Conn        dockertypes.HijackedResponse
	ctx         context.Context
	cancel      context.CancelFunc
	sendEvent   func(string, interface{}) error
	log         *logrus.Logger
}

// ShellHandler manages interactive shell sessions
type ShellHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger
	sendEvent    func(string, interface{}) error

	sessions   map[string]*ShellSession
	sessionsMu sync.RWMutex
}

// NewShellHandler creates a new shell handler
func NewShellHandler(dockerClient *docker.Client, log *logrus.Logger, sendEvent func(string, interface{}) error) *ShellHandler {
	return &ShellHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
		sessions:     make(map[string]*ShellSession),
	}
}

// HandleCommand processes a shell session command from the backend
func (h *ShellHandler) HandleCommand(ctx context.Context, cmd types.ShellSessionCommand) {
	switch cmd.Action {
	case "start":
		h.startSession(ctx, cmd.ContainerID, cmd.SessionID)
	case "data":
		h.writeData(cmd.SessionID, cmd.Data)
	case "resize":
		h.resize(cmd.SessionID, cmd.Cols, cmd.Rows)
	case "close":
		h.closeSession(cmd.SessionID)
	default:
		h.log.WithField("action", cmd.Action).Warn("Unknown shell session action")
	}
}

// startSession starts a new shell session for a container
func (h *ShellHandler) startSession(parentCtx context.Context, containerID, sessionID string) {
	h.sessionsMu.Lock()

	// Check if session already exists
	if _, exists := h.sessions[sessionID]; exists {
		h.sessionsMu.Unlock()
		h.log.WithField("session_id", sessionID).Warn("Shell session already exists")
		return
	}

	// Create context for this session
	ctx, cancel := context.WithCancel(parentCtx)

	session := &ShellSession{
		SessionID:   sessionID,
		ContainerID: containerID,
		ctx:         ctx,
		cancel:      cancel,
		sendEvent:   h.sendEvent,
		log:         h.log,
	}

	h.sessions[sessionID] = session
	h.sessionsMu.Unlock()

	// Start shell in goroutine
	go h.runShellSession(session)
}

// runShellSession runs the shell session (blocking)
func (h *ShellHandler) runShellSession(session *ShellSession) {
	defer func() {
		// Clean up session on exit
		h.sessionsMu.Lock()
		delete(h.sessions, session.SessionID)
		h.sessionsMu.Unlock()

		if session.Conn.Conn != nil {
			session.Conn.Close()
		}
	}()

	h.log.WithFields(logrus.Fields{
		"session_id":   session.SessionID,
		"container_id": safeShortID(session.ContainerID),
	}).Info("Starting shell session")

	// Create exec instance with bash (fallback to sh)
	execResp, err := h.dockerClient.ExecCreate(session.ctx, session.ContainerID, docker.ExecConfig{
		Cmd:          []string{"/bin/sh", "-c", "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi"},
		AttachStdin:  true,
		AttachStdout: true,
		AttachStderr: true,
		Tty:          true,
		Env:          []string{"TERM=xterm-256color"},
	})
	if err != nil {
		h.log.WithError(err).Error("Failed to create exec instance")
		h.sendEvent("shell_data", types.ShellDataEvent{
			SessionID: session.SessionID,
			Action:    "error",
			Error:     "Failed to create shell: " + err.Error(),
		})
		return
	}

	session.ExecID = execResp.ID

	// Attach to exec instance
	conn, err := h.dockerClient.ExecAttach(session.ctx, execResp.ID, true)
	if err != nil {
		h.log.WithError(err).Error("Failed to attach to exec instance")
		h.sendEvent("shell_data", types.ShellDataEvent{
			SessionID: session.SessionID,
			Action:    "error",
			Error:     "Failed to attach to shell: " + err.Error(),
		})
		return
	}
	session.Conn = conn

	// Notify backend that session started
	h.sendEvent("shell_data", types.ShellDataEvent{
		SessionID: session.SessionID,
		Action:    "started",
	})

	// Read from Docker and send to backend
	h.readLoop(session)

	// Session ended
	h.log.WithField("session_id", session.SessionID).Info("Shell session ended")
	h.sendEvent("shell_data", types.ShellDataEvent{
		SessionID: session.SessionID,
		Action:    "closed",
	})
}

// readLoop reads from Docker exec and forwards to backend
func (h *ShellHandler) readLoop(session *ShellSession) {
	buf := make([]byte, 4096)

	for {
		select {
		case <-session.ctx.Done():
			return
		default:
		}

		// Read from Docker
		n, err := session.Conn.Reader.Read(buf)
		if err != nil {
			if err != io.EOF {
				h.log.WithError(err).Debug("Shell read ended")
			}
			return
		}

		if n > 0 {
			// Encode data as base64 and send to backend
			encoded := base64.StdEncoding.EncodeToString(buf[:n])
			if err := h.sendEvent("shell_data", types.ShellDataEvent{
				SessionID: session.SessionID,
				Action:    "data",
				Data:      encoded,
			}); err != nil {
				h.log.WithError(err).Warn("Failed to send shell data to backend")
				return
			}
		}
	}
}

// writeData writes data to a shell session
func (h *ShellHandler) writeData(sessionID, data string) {
	h.sessionsMu.RLock()
	session, exists := h.sessions[sessionID]
	h.sessionsMu.RUnlock()

	if !exists {
		h.log.WithField("session_id", sessionID).Debug("Shell session not found for write")
		return
	}

	// Decode base64 data
	decoded, err := base64.StdEncoding.DecodeString(data)
	if err != nil {
		h.log.WithError(err).Warn("Failed to decode shell input data")
		return
	}

	// Write to Docker
	if session.Conn.Conn != nil {
		_, err = session.Conn.Conn.Write(decoded)
		if err != nil {
			h.log.WithError(err).Warn("Failed to write to shell session")
		}
	}
}

// resize resizes the shell session TTY
func (h *ShellHandler) resize(sessionID string, cols, rows int) {
	h.sessionsMu.RLock()
	session, exists := h.sessions[sessionID]
	h.sessionsMu.RUnlock()

	if !exists {
		h.log.WithField("session_id", sessionID).Debug("Shell session not found for resize")
		return
	}

	if session.ExecID == "" {
		return
	}

	err := h.dockerClient.ExecResize(session.ctx, session.ExecID, uint(rows), uint(cols))
	if err != nil {
		h.log.WithError(err).Warn("Failed to resize shell session")
	}
}

// closeSession closes a shell session
func (h *ShellHandler) closeSession(sessionID string) {
	h.sessionsMu.Lock()
	session, exists := h.sessions[sessionID]
	if exists {
		delete(h.sessions, sessionID)
	}
	h.sessionsMu.Unlock()

	if exists && session.cancel != nil {
		session.cancel()
	}

	h.log.WithField("session_id", sessionID).Info("Shell session closed")
}

// CloseAll closes all active shell sessions
func (h *ShellHandler) CloseAll() {
	h.sessionsMu.Lock()
	defer h.sessionsMu.Unlock()

	for sessionID, session := range h.sessions {
		if session.cancel != nil {
			session.cancel()
		}
		h.log.WithField("session_id", sessionID).Debug("Closed shell session")
	}
	h.sessions = make(map[string]*ShellSession)
	h.log.Info("Closed all shell sessions")
}
