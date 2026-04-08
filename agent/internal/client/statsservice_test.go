package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/sirupsen/logrus"
)

func TestStatsServiceClient_SendsMessages(t *testing.T) {
	upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
	var got []map[string]interface{}
	var mu sync.Mutex
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			http.Error(w, "missing auth", http.StatusUnauthorized)
			return
		}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		for {
			var msg map[string]interface{}
			if err := conn.ReadJSON(&msg); err != nil {
				return
			}
			mu.Lock()
			got = append(got, msg)
			mu.Unlock()
		}
	}))
	defer srv.Close()

	log := logrus.New()
	log.SetOutput(&testLogWriter{t})
	c := NewStatsServiceClient(srv.URL, "test-token", log)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go c.Run(ctx)

	c.Send(AgentStatsMsg{ContainerID: "abc123abc123", CPUPercent: 42.0})

	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		mu.Lock()
		if len(got) == 1 {
			if got[0]["container_id"] != "abc123abc123" {
				t.Errorf("container_id=%v, want abc123abc123", got[0]["container_id"])
			}
			mu.Unlock()
			return
		}
		mu.Unlock()
		time.Sleep(10 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	t.Errorf("got %d messages after 500ms, want 1", len(got))
}

func TestStatsServiceClient_DropsWhenChannelFull(t *testing.T) {
	log := logrus.New()
	log.SetOutput(&testLogWriter{t})
	c := NewStatsServiceClient("ws://localhost:0/never", "tok", log)
	// Don't run the client; spam the send channel.
	for i := 0; i < 10000; i++ {
		c.Send(AgentStatsMsg{ContainerID: "abc123abc123"})
	}
	// Test passes if we don't deadlock.
}

func TestNewStatsServiceClient_BuildsWsURL(t *testing.T) {
	log := logrus.New()
	log.SetOutput(&testLogWriter{t})

	cases := []struct {
		input  string
		prefix string
	}{
		{"https://dockmon.example.com", "wss://"},
		{"http://localhost:8001", "ws://"},
		{"https://dockmon.example.com/", "wss://"}, // trailing slash trimmed
	}
	for _, tc := range cases {
		c := NewStatsServiceClient(tc.input, "tok", log)
		if !strings.HasPrefix(c.url, tc.prefix) {
			t.Errorf("%s -> url=%q, want %s prefix", tc.input, c.url, tc.prefix)
		}
		if !strings.HasSuffix(c.url, "/api/stats/ws/ingest") {
			t.Errorf("%s -> url=%q, want /api/stats/ws/ingest suffix", tc.input, c.url)
		}
	}
}

func TestStatsServiceClient_ReconnectsAfterServerDisconnect(t *testing.T) {
	upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
	var connectCount int
	var mu sync.Mutex
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		connectCount++
		n := connectCount
		mu.Unlock()

		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		if n == 1 {
			// First connection: close immediately to trigger reconnect.
			conn.Close()
			return
		}
		// Second connection: hold it open briefly.
		defer conn.Close()
		_, _, _ = conn.ReadMessage()
	}))
	defer srv.Close()

	log := logrus.New()
	log.SetOutput(&testLogWriter{t})
	c := NewStatsServiceClient(srv.URL, "test-token", log)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go c.Run(ctx)

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		count := connectCount
		mu.Unlock()
		if count >= 2 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	t.Errorf("got %d connection attempts, want >= 2 (reconnect did not fire)", connectCount)
}

// testLogWriter pipes logrus output to the testing.T so it's visible on failure
// without spamming on pass.
type testLogWriter struct {
	t *testing.T
}

func (w *testLogWriter) Write(p []byte) (int, error) {
	w.t.Log(strings.TrimRight(string(p), "\n"))
	return len(p), nil
}
