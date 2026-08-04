package main

import (
	"encoding/json"
	"log"
	"net/http"
)

// dockerHostAdder is the slice of StreamManager the add-host endpoint needs.
type dockerHostAdder interface {
	AddDockerHost(hostID, hostName, hostAddress, tlsCACert, tlsCert, tlsKey string) error
	RemoveDockerHost(hostID string)
}

// agentSessionRegistry reports whether an agent currently owns a host_id.
type agentSessionRegistry interface {
	HasActiveSession(hostID string) bool
}

// makeHostsAddHandler builds the /api/hosts/add handler. sessions may be nil
// when the ingest endpoint is not mounted (persistence disabled).
//
// A host is either agent-owned or Docker-registered, never both: the aggregator
// writes the host cache only for registered Docker hosts, ingest writes it only
// for agents, and both use the same key.
func makeHostsAddHandler(hosts dockerHostAdder, cache *StatsCache, sessions agentSessionRegistry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID      string `json:"host_id"`
			HostName    string `json:"host_name"`
			HostAddress string `json:"host_address"`
			TLSCACert   string `json:"tls_ca_cert,omitempty"`
			TLSCert     string `json:"tls_cert,omitempty"`
			TLSKey      string `json:"tls_key,omitempty"`
			NumCPUs     int    `json:"num_cpus,omitempty"`
			TotalMemory uint64 `json:"total_memory,omitempty"`
			IsLocal     bool   `json:"is_local,omitempty"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		if req.HostID == "" || req.HostName == "" || req.HostAddress == "" {
			http.Error(w, "host_id, host_name, and host_address are required", http.StatusBadRequest)
			return
		}

		if sessions != nil && sessions.HasActiveSession(req.HostID) {
			rejectAgentOwnedHost(w, req.HostID)
			return
		}

		if err := hosts.AddDockerHost(req.HostID, req.HostName, req.HostAddress, req.TLSCACert, req.TLSCert, req.TLSKey); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		// An agent that connected during the registration would have checked
		// for a Docker host before this one existed, so re-check after acting:
		// either we see its session here, or its own check ran after the
		// registration landed and evicted us.
		if sessions != nil && sessions.HasActiveSession(req.HostID) {
			hosts.RemoveDockerHost(req.HostID)
			rejectAgentOwnedHost(w, req.HostID)
			return
		}

		if req.NumCPUs > 0 {
			cache.SetHostNumCPUs(req.HostID, req.NumCPUs)
		}
		if req.TotalMemory > 0 {
			cache.SetHostMemory(req.HostID, req.TotalMemory)
		}
		if req.IsLocal {
			cache.SetHostLocal(req.HostID, true)
		}

		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "added"})
	}
}

func rejectAgentOwnedHost(w http.ResponseWriter, hostID string) {
	log.Printf("Rejected Docker host registration for %s: an agent holds this host_id",
		truncateID(hostID, 8))
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusConflict)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error": "host_id is owned by a connected agent",
	})
}
