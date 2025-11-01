# DOCKMON AGENT CODEBASE ARCHITECTURE REVIEW

## Executive Summary

DockMon v2.2.0 implements a distributed agent architecture that allows remote Docker host management through WebSocket connections. The system consists of:

1. **Agent (Go)**: Runs on remote Docker hosts, collects metrics, manages containers, and communicates via WebSocket
2. **Backend (Python)**: Manages agent lifecycle, routes commands, and persists agent state
3. **WebSocket Protocol**: Real-time bidirectional communication with correlation ID-based request/response pattern

Total Agent Codebase: ~1,965 lines of Go code

---

## PART 1: AGENT ARCHITECTURE (Go - /root/dockmon/agent)

### Directory Structure
```
/root/dockmon/agent/
├── cmd/agent/
│   └── main.go                 # Entry point, initialization
├── internal/
│   ├── client/
│   │   └── websocket.go        # WebSocket connection manager
│   ├── config/
│   │   └── config.go           # Configuration loading from env vars
│   ├── docker/
│   │   └── client.go           # Docker API wrapper
│   ├── handlers/
│   │   ├── update.go           # Container update logic
│   │   ├── selfupdate.go       # Agent self-update logic
│   │   └── stats.go            # Container stats collection
│   └── protocol/
│       └── protocol.go         # Message encoding/decoding
├── pkg/types/
│   └── types.go                # Message type definitions
├── go.mod                       # Go module definition
├── Dockerfile                   # Docker image build
└── go.sum                       # Dependency lock file
```

### Key Components

#### 1. MAIN ENTRY POINT (cmd/agent/main.go - 127 lines)
**Purpose**: Initialize agent and establish backend connection
**Critical Path**:
1. Load config from environment variables
2. Setup logging (JSON or text)
3. Create Docker client connection
4. Get Docker engine ID (unique identifier)
5. Detect agent's own container ID (for self-update)
6. Create WebSocket client
7. Check for pending self-updates
8. Run WebSocket client in background
9. Handle shutdown signals

**Key Code Flow**:
```go
- config.LoadFromEnv() -> loads DOCKMON_URL, tokens, Docker config
- docker.NewClient(cfg) -> connects to Docker socket
- client.NewWebSocketClient() -> initializes WebSocket handler
- wsClient.CheckPendingUpdate() -> checks for interrupted updates
- wsClient.Run(ctx) -> main connection loop with auto-reconnect
```

**Configuration Sources**:
- `DOCKMON_URL` (required): Backend WebSocket endpoint
- `REGISTRATION_TOKEN` or `PERMANENT_TOKEN` (one required)
- `DOCKER_HOST` (default: unix:///var/run/docker.sock)
- `LOG_LEVEL`, `LOG_JSON` (logging config)
- `RECONNECT_INITIAL`, `RECONNECT_MAX` (exponential backoff: 1s → 60s)

---

#### 2. CONFIGURATION MODULE (internal/config/config.go - 123 lines)
**Purpose**: Centralized configuration management
**Key Responsibilities**:
- Load environment variables
- Validate required fields
- Provide defaults
- Load persistent tokens from /data/permanent_token file

**Token Handling**:
1. Priority: PERMANENT_TOKEN env var > /data/permanent_token file > REGISTRATION_TOKEN
2. Persistent storage at `/data/permanent_token` (0600 permissions - owner only)
3. Used for agent re-identification on reconnection

**Validation**:
- Requires DOCKMON_URL
- Requires either REGISTRATION_TOKEN (first registration) or PERMANENT_TOKEN (reconnection)
- Logs validation failures to stderr

---

#### 3. MESSAGE TYPES (pkg/types/types.go - 101 lines)
**Purpose**: Strongly typed message definitions for WebSocket protocol

**Key Structures**:

```go
// Message - WebSocket envelope
type Message struct {
  Type      string            // "command", "response", "event"
  ID        string            // Correlation ID
  Command   string            // Command name
  Payload   interface{}       // Command parameters
  Error     string            // Error message
  Timestamp time.Time         // ISO 8601 timestamp
}

// RegistrationRequest - Initial authentication message
type RegistrationRequest struct {
  Token        string
  EngineID     string
  Hostname     string
  Version      string
  ProtoVersion string
  Capabilities map[string]bool
  // System info (v2.2.0)
  OSType, OSVersion, KernelVersion, DockerVersion
  DaemonStartedAt string
  TotalMemory  int64
  NumCPUs      int
}

// ContainerStats - Per-container metrics
type ContainerStats struct {
  ContainerID    string
  Timestamp      time.Time
  CPUPercent, MemoryUsage, MemoryLimit, MemoryPercent float64
  NetworkRx, NetworkTx, BlockRead, BlockWrite uint64
}

// SelfUpdateCommand - Agent self-update payload
type SelfUpdateCommand struct {
  NewImage    string  // New agent image
  ImageDigest string  // Image digest for verification
}
```

---

#### 4. WEBSOCKET CLIENT (internal/client/websocket.go - 729 lines)
**Purpose**: Core communication engine with automatic reconnection

**Architecture**:
```
WebSocketClient
├── Connection Management
│   ├── connect()           - Establish WS connection
│   ├── register()          - Send auth message
│   ├── handleConnection()  - Main message loop
│   └── closeConnection()   - Cleanup
├── Message Handling
│   ├── handleMessage()              - Dispatch to handlers
│   ├── handleContainerOperation()   - v2.2.0 container ops
│   └── streamEvents()               - Docker event streaming
├── Handlers (dependency injection)
│   ├── statsHandler         - Collect container metrics
│   ├── updateHandler        - Update containers
│   └── selfUpdateHandler    - Update agent itself
└── Communication
    ├── sendMessage()  - Send typed Message
    ├── sendJSON()     - Send raw JSON (v2.2.0)
    └── sendEvent()    - Helper for event messages
```

**Connection Lifecycle**:
1. **Connect Phase**:
   - WebSocket dial to wss://backend/api/agent/ws
   - Send registration/reconnection message
   - Wait for response with agent_id

2. **Active Phase**:
   - Start stats collection for all containers
   - Start Docker event streaming
   - Process incoming commands in loop
   - Auto-reconnect on disconnect

3. **Command Dispatch** (handleMessage):
   - `ping` → return pong
   - `get_system_info` → collect fresh system data
   - `list_containers` → Docker API call
   - `start/stop/restart/delete_container` → Container operations
   - `update_container` → Rolling update (background)
   - `self_update` → Self-update (background)

4. **Container Operations** (v2.2.0 - handleContainerOperation):
   - **New Message Type**: "container_operation" (not "command")
   - **Parameters**: action, container_id, correlation_id
   - **Actions**: start, stop, restart, remove, get_logs, inspect
   - **Response**: Raw JSON with correlation_id for backend matching

**Registration Message Format**:
```json
{
  "type": "register",
  "token": "uuid",
  "engine_id": "docker-engine-sha256",
  "hostname": "docker-host.local",
  "version": "2.2.0",
  "proto_version": "1.0",
  "capabilities": {
    "container_operations": true,
    "container_updates": true,
    "event_streaming": true,
    "stats_collection": true,
    "self_update": true
  },
  "os_type": "linux",
  "os_version": "Ubuntu 22.04.3 LTS",
  "kernel_version": "5.15.0-88-generic",
  "docker_version": "24.0.6",
  "daemon_started_at": "2025-10-30T11:55:52.337598034Z",
  "total_memory": 8589934592,
  "num_cpus": 4
}
```

**Critical Bug Risk**: Token Persistence
- Line 318: Logs fatal error if token cannot be persisted to /data/permanent_token
- Requires `-v agent-data:/data` volume mount in Docker
- Without persistence: Agent loses identity on container restart

---

#### 5. PROTOCOL (internal/protocol/protocol.go - 59 lines)
**Purpose**: Message encoding/decoding utilities

**Functions**:
- `EncodeMessage(msg)` → JSON bytes with timestamp
- `DecodeMessage(bytes)` → Typed Message struct
- `NewCommandResponse(id, payload, err)` → Create response envelope
- `NewEvent(type, payload)` → Create event message
- `ParseCommand(msg, target)` → Unmarshal payload to struct

---

#### 6. DOCKER CLIENT (internal/docker/client.go - 329 lines)
**Purpose**: Docker API abstraction with agent-specific operations

**Key Methods**:
```go
// Connection & Discovery
GetEngineID(ctx)              // Unique Docker daemon ID
GetSystemInfo(ctx)            // Host metadata (matches schema)
GetMyContainerID(ctx)         // Read from /proc/self/cgroup
ListContainers(ctx)           // All containers (all states)
InspectContainer(ctx, id)     // Detailed container info

// Container Operations
StartContainer(ctx, id)
StopContainer(ctx, id, timeout)
RestartContainer(ctx, id, timeout)
RemoveContainer(ctx, id, force)
GetContainerLogs(ctx, id, tail)
ContainerStats(ctx, id, stream) // Streaming stats

// Image Operations
PullImage(ctx, image)         // Download image
CreateContainer(ctx, ...)     // Create new container

// Event Streaming
WatchEvents(ctx)              // Docker event channel
```

**System Information Collection**:
Matches fields stored in DockerHostDB schema:
- `Hostname` → From Docker info.Name (NOT container hostname)
- `OSType`, `OSVersion`, `KernelVersion` → Docker daemon info
- `DockerVersion` → ServerVersion
- `DaemonStartedAt` → From bridge network creation time
- `TotalMemory`, `NumCPUs` → Hardware resources

**Notable Implementation**:
- Uses shared package for Docker client creation (dockmon-shared)
- Simplified cgroup parser for container ID extraction
- No TLS implementation for remote hosts (TODO)

---

#### 7. HANDLERS (internal/handlers/)

##### 7.1 STATS HANDLER (handlers/stats.go - 170 lines)
**Purpose**: Real-time container metrics collection and streaming

**Architecture**:
```
StatsHandler
├── StartStatsCollection()     - Begin tracking all running containers
├── StartContainerStats()      - Start individual container stream
├── StopContainerStats()       - Stop individual stream
├── StopAll()                  - Cleanup all streams
├── collectStats()             - Streaming loop (goroutine per container)
└── processStats()             - Calculate metrics and send
```

**Metrics Sent**:
```json
{
  "type": "event",
  "command": "container_stats",
  "payload": {
    "container_id": "abc123",
    "container_name": "my-service",
    "cpu_percent": 2.5,
    "memory_usage": 134217728,
    "memory_limit": 2147483648,
    "memory_percent": 6.25,
    "network_rx": 1024000,
    "network_tx": 2048000,
    "disk_read": 512000,
    "disk_write": 1024000,
    "timestamp": "2025-10-31T12:00:00Z"
  }
}
```

**Key Features**:
- Uses shared package for stats calculation (consistent with stats-service)
- Per-container goroutines with cancellable contexts
- RoundToDecimal() for clean percentage values
- Automatic lifecycle management (start on container start, stop on die/stop/kill)

---

##### 7.2 UPDATE HANDLER (handlers/update.go - 279 lines)
**Purpose**: Rolling container updates with health checks

**Update Flow**:
1. **Inspect** old container for configuration
2. **Pull** new image
3. **Create** new container with cloned config (append "-new" to name)
4. **Start** new container
5. **Health Check** with timeout (30s default)
6. **Stop** old container gracefully (10s timeout)
7. **Remove** old container
8. (Optional) Rename new container to original name

**Health Check Strategy**:
- If container has healthcheck defined: Monitor Docker health status
- If no healthcheck: Wait 5 seconds (assume healthy)
- Timeout: 30 seconds by default
- **Rollback on failure**: Stop and remove new container, keep old running

**Configuration Cloning**:
Copies from old container config:
- Environment variables
- Command, entrypoint, working directory
- Port bindings, volume mounts
- Restart policy, resource limits
- DNS, extra hosts, capabilities
- Labels, user, hostname

**Progress Events**:
Sends progress updates after each stage:
```json
{
  "type": "event",
  "command": "update_progress",
  "payload": {
    "container_id": "abc123",
    "stage": "pull|create|start|health|stop_old|remove_old|complete",
    "message": "Human-readable message",
    "error": "Optional error details"
  }
}
```

---

##### 7.3 SELF-UPDATE HANDLER (handlers/selfupdate.go - 283 lines)
**Purpose**: In-place agent binary replacement

**Two-Phase Update**:
1. **Preparation Phase** (PerformSelfUpdate):
   - Download new binary to /data/agent-new
   - Verify checksum (TODO: not implemented)
   - Write /data/update.lock with metadata
   - Return control to main loop
   - Main process exits

2. **Application Phase** (CheckAndApplyUpdate - on startup):
   - Read /data/update.lock
   - Backup old binary: /app/agent → /app/agent.backup
   - Replace: /app/agent-new → /app/agent
   - Remove /data/update.lock
   - Resume normal operation

**Update Lock File Format**:
```json
{
  "version": "2.2.0",
  "new_binary_path": "/data/agent-new",
  "old_binary_path": "/app/agent",
  "timestamp": "2025-10-31T12:00:00Z"
}
```

**Critical Dependencies**:
- Binary at `/app/agent` (baked into container image)
- Writable /data volume mount
- Container restart capability (Docker daemon or orchestrator)

**Known Limitations**:
- Checksum verification not implemented (security risk)
- No atomic swap (potential corruption if process crashes mid-replacement)
- Single-byte binary difference causes full re-download
- No automatic rollback if new binary fails to start

---

### Cross-Cutting Concerns

#### Logging
- Structured logging with logrus
- JSON format (configurable via LOG_JSON env var)
- Log level: DEBUG, INFO, WARN, ERROR via LOG_LEVEL
- All operations include context fields (container_id, agent_id, etc.)

#### Error Handling
- Context-aware error propagation
- Most operations fail fast with descriptive errors
- Long-running ops (update) send progress events on error
- Connection errors trigger auto-reconnect with exponential backoff

#### Concurrency
- **Goroutines**: Event streaming, stats collection per container, async command handlers
- **Mutexes**: RWMutex for WebSocket connection (connMu)
- **Channels**: Stop signals, error channels from Docker API
- **Context**: Cancellation for graceful shutdown

---

## PART 2: BACKEND ARCHITECTURE (Python - /root/dockmon/backend)

### Agent-Related Files
```
/root/dockmon/backend/
├── agent/
│   ├── __init__.py
│   ├── manager.py             # Registration & token validation
│   ├── models.py              # Pydantic validation models
│   ├── connection_manager.py  # Track active agent connections
│   ├── websocket_handler.py   # WebSocket endpoint handler
│   ├── command_executor.py    # Request/response pattern for commands
│   └── container_operations.py # High-level container ops
├── database.py                 # SQLAlchemy models (Agent, RegistrationToken, DockerHostDB)
├── websocket/
│   ├── __init__.py
│   └── connection.py          # UI WebSocket manager (separate from agent)
└── main.py                     # FastAPI app initialization
```

### Database Models (database.py)

#### RegistrationToken Table
```sql
CREATE TABLE registration_tokens (
  id INTEGER PRIMARY KEY,
  token VARCHAR UNIQUE NOT NULL,        -- UUID
  created_by_user_id INTEGER NOT NULL,  -- FK users.id
  created_at DATETIME NOT NULL,
  expires_at DATETIME NOT NULL,         -- 15-minute expiry
  used BOOLEAN DEFAULT FALSE,
  used_at DATETIME NULL
)
```

**Lifecycle**:
1. Created: User requests registration via UI
2. Used for registration: Agent sends token in first auth message
3. Marked as used: Backend sets used=true after successful registration
4. Cleaned up: Expired tokens remain in DB (for audit)

---

#### Agent Table
```sql
CREATE TABLE agents (
  id VARCHAR PRIMARY KEY,               -- UUID generated by backend
  host_id VARCHAR UNIQUE NOT NULL,      -- FK docker_hosts.id
  engine_id VARCHAR UNIQUE NOT NULL,    -- Unique per Docker daemon
  version VARCHAR NOT NULL,             -- Agent semantic version
  proto_version VARCHAR NOT NULL,       -- Protocol version for compatibility
  capabilities JSON NOT NULL,           -- {"stats_collection": true, ...}
  status VARCHAR NOT NULL,              -- 'online', 'offline', 'degraded'
  last_seen_at DATETIME NOT NULL,
  registered_at DATETIME NOT NULL
)
```

**Unique Constraints**:
- `id`: Backend-assigned UUID (regenerated each registration)
- `engine_id`: Unique per Docker daemon (identifies same daemon across reconnections)
- `host_id`: One-to-one relationship with DockerHostDB

**Status Values**:
- `online`: Agent connected and responsive
- `offline`: Agent disconnected (marked after 5+ minute timeout)
- `degraded`: Agent connected but some capabilities unavailable

---

#### DockerHostDB Table (Extended in v2.2.0)
```sql
ALTER TABLE docker_hosts ADD COLUMN (
  connection_type VARCHAR DEFAULT 'local',  -- 'local', 'mtls', 'agent' (v2.2.0)
  os_type VARCHAR,
  os_version VARCHAR,
  kernel_version VARCHAR,
  docker_version VARCHAR,
  daemon_started_at VARCHAR,              -- ISO timestamp
  total_memory BIGINT,
  num_cpus INTEGER
)
```

**Relationship to Agent**:
- One-to-one via host_id
- When agent registers: Host record created with system info
- When agent reconnects: Host record updated with fresh system info

---

### Agent Manager (agent/manager.py - 345 lines)

**Purpose**: Agent registration, authentication, token validation

**Key Methods**:

1. **generate_registration_token(user_id)**
   - Creates single-use UUID token
   - Expires in 15 minutes
   - Returns RegistrationToken record

2. **validate_registration_token(token)**
   - Check token exists in DB
   - Check token not already used
   - Check expiration (now <= expires_at)
   - Returns bool

3. **validate_permanent_token(token)**
   - Check agent_id exists (token == agent.id)
   - Used for reconnection

4. **register_agent(registration_data)**
   - Validates token (registration or permanent)
   - If permanent token: Update existing agent with fresh system info
   - If registration token: Create new Agent + DockerHostDB records
   - Mark token as used
   - Returns: {success, agent_id, host_id, permanent_token}

5. **reconnect_agent(reconnect_data)**
   - Validate agent_id exists
   - Validate engine_id matches stored value (security check)
   - Update last_seen_at, status='online'
   - Returns: {success, agent_id}

6. **get_agent_for_host(host_id)**
   - Lookup agent by host_id
   - Returns agent_id or None

**Database Session Pattern**:
- Creates NEW session for each operation (not persistent)
- Follows DockMon's short-lived session pattern
- Flush before nested operations (FK dependencies)
- Commit at end of registration (dedicated session)

---

### Agent Validation Models (agent/models.py - 111 lines)

**Purpose**: Input validation, XSS prevention, DoS protection

**Class: AgentRegistrationRequest**

**Fields**:
```python
type: str                       # Pattern: "^register$" (literal string)
token: str                      # max_length=255
engine_id: str                  # max_length=255
version: str                    # max_length=50
proto_version: str              # max_length=20
capabilities: Dict[str, bool]
hostname: Optional[str]         # max_length=255
os_type: Optional[str]          # max_length=50
os_version: Optional[str]       # max_length=500
kernel_version: Optional[str]   # max_length=255
docker_version: Optional[str]   # max_length=50
daemon_started_at: Optional[str] # max_length=100
total_memory: Optional[int]     # Range: 1 to 1PB
num_cpus: Optional[int]         # Range: 1 to 10,000
```

**Validation Rules**:
1. **HTML Sanitization**: Remove `<>` from string fields
2. **Printable Character Check**: Remove non-printable chars
3. **ID Validation**: engine_id, token must match `^[a-zA-Z0-9\-_]+$`
4. **Timestamp Validation**: daemon_started_at max 100 chars (truncate)
5. **No Extra Fields**: extra='forbid' prevents injection

**Security Properties**:
- Prevents XSS: `<script>` becomes `script`
- Prevents type confusion: Pydantic enforces type matching
- Prevents DoS: Length limits prevent oversized payloads
- Prevents injection: ID regex blocks special characters

---

### Agent Connection Manager (agent/connection_manager.py - 147 lines)

**Purpose**: Track active WebSocket connections to agents

**Architecture**:
- Singleton pattern (one per backend process)
- Thread-safe with asyncio.Lock()
- Maps agent_id → WebSocket connection

**Key Methods**:

1. **register_connection(agent_id, websocket)**
   - Store websocket in connections dict
   - Update agent.status='online' in DB
   - Close any existing connection for this agent_id

2. **unregister_connection(agent_id)**
   - Remove from connections dict
   - Update agent.status='offline' in DB

3. **send_command(agent_id, command)**
   - Lookup websocket from dict
   - Send command JSON to agent
   - Return success bool
   - Logs connection errors (dead connections cleaned up on next heartbeat)

4. **is_connected(agent_id)**
   - Return bool: agent_id in connections

5. **get_connected_agent_ids()**
   - Return list of connected agent IDs

6. **get_connection_count()**
   - Return number of connected agents

**Critical Design**:
- Does NOT persist connections across restarts
- If backend restarts: All agents forced to reconnect
- Websocket objects are not serializable

---

### Agent WebSocket Handler (agent/websocket_handler.py - 275 lines)

**Purpose**: Handle WebSocket connections from agents

**Entry Point** (main.py line 3973):
```python
@app.websocket("/api/agent/ws")
async def agent_websocket_endpoint(websocket: WebSocket):
    await handle_agent_websocket(websocket)
```

**Connection Lifecycle**:

1. **Accept & Authenticate** (30s timeout):
   - Accept WebSocket connection
   - Wait for auth message (register or reconnect)
   - Validate message against AgentRegistrationRequest
   - Call agent_manager.register_agent() or reconnect_agent()

2. **Send Auth Response**:
   - Success: Send {type: "auth_success", agent_id, host_id, permanent_token}
   - Failure: Send {type: "auth_error", error: "message"}, close connection

3. **Register in Connection Manager**:
   - Store WebSocket in AgentConnectionManager
   - Mark agent as 'online' in DB

4. **Message Loop**:
   - Receive messages from agent (stats, progress, events, heartbeat)
   - Call handle_agent_message() to process
   - Continue until disconnect

5. **Cleanup**:
   - Unregister connection
   - Mark agent as 'offline'
   - Close WebSocket

**Message Types from Agent**:
```python
msg_type == "stats"        # Container stats (TODO: forward to monitoring)
msg_type == "progress"     # Update progress event (TODO: forward to UI)
msg_type == "error"        # Operation error (TODO: notify user)
msg_type == "heartbeat"    # Keep-alive (update last_seen_at)
msg_type == "event"        # Container events, stats (see below)
```

**Event Message Format**:
```python
event_type = message.get("command")  # Type of event
payload = message.get("payload")     # Event data

if event_type == "container_event":
    # Docker container lifecycle: start, stop, die, health_status
    # TODO: Store in DB, trigger alerts, broadcast to UI
    
elif event_type == "container_stats":
    # Real-time metrics
    # TODO: Store in stats history, broadcast to UI
```

---

### Command Executor (agent/command_executor.py - 297 lines)

**Purpose**: Send commands to agents and wait for responses with timeout

**Design Pattern**: Request/Response with Correlation IDs

**Architecture**:
```
execute_command(agent_id, command, timeout=30s)
├── Generate correlation_id (UUID)
├── Register asyncio.Future() for correlation_id
├── Send command + correlation_id to agent via ConnectionManager
├── Wait for response with timeout
└── Clean up pending command
```

**Implementation Details**:
- `_pending_commands`: Dict[correlation_id, {future, agent_id, started_at}]
- Uses asyncio.Future for async waiting
- Timeouts tracked per command (not per agent)
- Auto-cleanup of expired commands (5 min default)

**CommandResult**:
```python
@dataclass
class CommandResult:
    status: CommandStatus          # SUCCESS, ERROR, TIMEOUT
    success: bool                  # Parsed from response
    response: Optional[Dict]       # Agent response payload
    error: Optional[str]           # Error message
    duration_seconds: float        # Elapsed time
```

**Correlation Flow**:
1. Backend sends: {type: "container_operation", correlation_id: "uuid-123", ...}
2. Agent processes command
3. Agent responds: {correlation_id: "uuid-123", success: true, ...}
4. Backend: handle_agent_response() looks up future for uuid-123
5. Future resolved: Waiting execute_command() returns CommandResult

---

### Container Operations (agent/container_operations.py - 509 lines)

**Purpose**: High-level container management via agents

**Key Methods**:

1. **start_container(host_id, container_id)**
2. **stop_container(host_id, container_id, timeout=10)**
3. **restart_container(host_id, container_id)**
4. **remove_container(host_id, container_id, force=False)**
5. **get_container_logs(host_id, container_id, tail=100)**
6. **inspect_container(host_id, container_id)**

**Pattern**:
1. Lookup agent_id from host_id
2. Build container_operation command
3. Execute via command_executor with timeout
4. Parse response status
5. Raise HTTPException on error

**Safety Checks**:
- Prevent stopping/restarting/removing DockMon itself
- Check container name: "dockmon" or "dockmon-*"
- Check label: app="dockmon"
- Fail-safe: If check fails, return False (don't assume it's safe)

**Error Handling**:
- Agent not connected: HTTPException 404
- Command timeout: HTTPException 504
- Command failed: HTTPException 500

---

## PART 3: WEBSOCKET PROTOCOL

### Message Types & Flows

#### Registration Flow

**Agent → Backend** (initial):
```json
{
  "type": "register",
  "token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "engine_id": "f2b6c7d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9",
  "hostname": "docker-prod.example.com",
  "version": "2.2.0",
  "proto_version": "1.0",
  "capabilities": {
    "container_operations": true,
    "container_updates": true,
    "event_streaming": true,
    "stats_collection": true,
    "self_update": true
  },
  "os_type": "linux",
  "os_version": "Ubuntu 22.04.3 LTS",
  "kernel_version": "5.15.0-88-generic",
  "docker_version": "24.0.6",
  "daemon_started_at": "2025-10-30T11:55:52.337598034Z",
  "total_memory": 8589934592,
  "num_cpus": 4
}
```

**Backend → Agent** (success):
```json
{
  "type": "auth_success",
  "agent_id": "agent-uuid-assigned-by-backend",
  "host_id": "host-uuid-for-docker-host",
  "permanent_token": "agent-uuid"
}
```

**Backend → Agent** (failure):
```json
{
  "type": "auth_error",
  "error": "Invalid registration token"
}
```

---

#### Container Operation Flow (v2.2.0)

**Backend → Agent**:
```json
{
  "type": "container_operation",
  "action": "start|stop|restart|remove|get_logs|inspect",
  "container_id": "abc123def456",
  "correlation_id": "cmd-uuid",
  "timeout": 10,  // For stop/restart
  "tail": 100,    // For get_logs
  "force": false  // For remove
}
```

**Agent → Backend**:
```json
{
  "type": "response",  // Deprecated? v2.2.0 uses raw JSON
  "correlation_id": "cmd-uuid",
  "success": true,
  "container_id": "abc123def456",
  "status": "started",
  // Additional fields per action
  "logs": "...",       // get_logs action
  "container": {...}   // inspect action
}
```

---

#### Stats Streaming

**Agent → Backend** (continuous):
```json
{
  "type": "event",
  "command": "container_stats",
  "payload": {
    "container_id": "abc123def456",
    "container_name": "nginx-prod",
    "cpu_percent": 2.5,
    "memory_usage": 134217728,
    "memory_limit": 2147483648,
    "memory_percent": 6.25,
    "network_rx": 1024000,
    "network_tx": 2048000,
    "disk_read": 512000,
    "disk_write": 1024000,
    "timestamp": "2025-10-31T12:00:00Z"
  }
}
```

---

#### Event Streaming

**Agent → Backend** (on container lifecycle change):
```json
{
  "type": "event",
  "command": "container_event",
  "payload": {
    "container_id": "abc123def456",
    "container_name": "nginx-prod",
    "image": "nginx:latest",
    "action": "start|stop|die|health_status|...",
    "status": "optional additional status",
    "timestamp": "2025-10-31T12:00:00Z",
    "attributes": {
      "name": "nginx-prod",
      "image": "nginx:latest",
      "exitCode": "0"  // on die event
    }
  }
}
```

---

## PART 4: CRITICAL ISSUES & SECURITY CONCERNS

### HIGH SEVERITY

#### 1. Missing Checksum Verification in Self-Update
**Location**: handlers/selfupdate.go line 77-81
**Issue**: Comment says "TODO: Implement checksum verification"
**Risk**: MITM attack - agent downloads and executes arbitrary binary
**Recommendation**: Implement SHA256 checksum validation before executing

#### 2. Unencrypted Permanent Token Storage
**Location**: internal/client/websocket.go line 317
**Issue**: Token stored in plain text to /data/permanent_token (0600 permissions)
**Risk**: Container breakout → read token → impersonate agent
**Recommendation**:
- Use encrypted storage (secretbox or similar)
- Rotate tokens periodically
- Implement token invalidation on compromise

#### 3. No TLS Implementation for Remote Agents
**Location**: internal/docker/client.go line 33-36
**Issue**: TLS configuration not implemented for Docker remote connections
**Risk**: Remote agents (non-local socket) communicate unencrypted
**Recommendation**: Complete TLS implementation with certificate validation

#### 4. Agent Can Execute Arbitrary Commands via Command Dispatch
**Location**: internal/client/websocket.go line 403-494
**Issue**: Backend can send any command - no authorization/rate limiting
**Risk**: Backend compromise → arbitrary container operations
**Recommendation**:
- Implement command ACL based on agent capabilities
- Rate limit command execution
- Log all commands for audit

### MEDIUM SEVERITY

#### 5. No Response Size Limits
**Location**: agent/command_executor.py - execute_command()
**Issue**: Container logs can be arbitrarily large (no max_length on "tail" param)
**Risk**: OOM if container has huge logs
**Recommendation**: Enforce max_length on log responses (e.g., 10MB)

#### 6. WebSocket Read Timeout Only on Registration
**Location**: internal/client/websocket.go line 277
**Issue**: SetReadDeadline only during registration, not during active message loop
**Risk**: Slow-read attack - backend holds connection open indefinitely
**Recommendation**: Set read timeout during message loop (e.g., 5 minutes)

#### 7. No Heartbeat from Agent
**Location**: internal/client/websocket.go
**Issue**: Backend detects disconnection only via read error
**Risk**: Dead connections kept open, resource leak
**Recommendation**: Implement agent-initiated heartbeat (e.g., every 30 seconds)

#### 8. Concurrent Map Access in StatsHandler
**Location**: handlers/stats.go line 22-27
**Issue**: `streams` map accessed with RWMutex, but concurrent goroutines read without lock
**Risk**: Potential data race during stats collection
**Recommendation**: Review lock usage in collectStats() flow

#### 9. SQL Injection via Config Injection
**Location**: agent/models.py - validate_ids()
**Issue**: ID fields validated with regex, but no SQLAlchemy ORM protection
**Risk**: If validation bypassed, SQL injection possible
**Recommendation**: Validation is good defense-in-depth, but use parameterized queries (SQLAlchemy already does this)

### LOW SEVERITY

#### 10. Update Lock File Not Atomic
**Location**: handlers/selfupdate.go line 147
**Issue**: File operations (Rename) not atomic - crash mid-replacement corrupts binary
**Risk**: Agent fails to start after incomplete update
**Recommendation**: Use atomic swap pattern or transactional filesystem operations

#### 11. Docker Event Parsing Fragile
**Location**: internal/client/websocket.go line 626-639
**Issue**: parseContainerIDFromCgroup() manually parses text - error-prone
**Risk**: Container ID misparsing → invalid self-update detection
**Recommendation**: Use cgroups library or more robust parsing

#### 12. No Automatic Agent Cleanup
**Location**: backend agent lifecycle
**Issue**: Offline agents remain in DB indefinitely
**Risk**: DB pollution, stale entries confuse UI
**Recommendation**: Auto-delete agents offline > 30 days, or implement soft-delete

---

## PART 5: INTEGRATION POINTS

### Backend Initialization (main.py line 3973)
```python
@app.websocket("/api/agent/ws")
async def agent_websocket_endpoint(websocket: WebSocket):
    await handle_agent_websocket(websocket)
```

### Agent Usage in Container Operations
```python
# From main.py or API handler
agent_ops = AgentContainerOperations(
    command_executor=executor,
    db=db_manager,
    agent_manager=agent_manager
)

# Start container via agent
await agent_ops.start_container(host_id, container_id)
```

### Agent Connection Singleton
```python
# Global instance in agent/connection_manager.py
agent_connection_manager = AgentConnectionManager()

# Used by WebSocket handler
await agent_connection_manager.register_connection(agent_id, websocket)
```

---

## PART 6: DATA FLOW DIAGRAM

```
┌─────────────┐                                    ┌──────────────┐
│   Agent     │                                    │   Backend    │
│  (Go 2.2.0) │                                    │  (Python)    │
└──────┬──────┘                                    └──────┬───────┘
       │                                                  │
       │ [1] RegistrationRequest                         │
       ├─────────────────────────────────────────────────>
       │ {token, engine_id, system_info}                │
       │                                                 │
       │                    [2] Validate Token          │
       │                 ┌───────────────────────┐      │
       │                 │ AgentManager.register │      │
       │                 │ - Check token (15min) │      │
       │                 │ - Create Agent record │      │
       │                 │ - Create DockerHost   │      │
       │                 └───────────────────────┘      │
       │                                                 │
       │ [3] AuthSuccess {agent_id, host_id}           │
       <─────────────────────────────────────────────────
       │                                                 │
       │ [4] Event Streaming + Stats                     │
       ├─ container_event ──────────────────────────────>
       │                     container_stats            │
       │                     (continuous)               │
       │                                                 │
       │ [5] Backend sends container_operation          │
       │     {action: "start", container_id}            │
       <──────────────────────────────────────────────────
       │                                                 │
       │ [6] Execute Docker operation, send response     │
       ├───────────────────────────────────────────────>
       │ {correlation_id, success, result}              │
       │                                                 │
       │ [7] Reconnect (if disconnected)                 │
       ├─ RegisterRequest {permanent_token, engine_id} ->
       │                                                 │
       │   Validate permanent_token = agent_id          │
       │   Validate engine_id matches                   │
       │                                                 │
       │ [8] AuthSuccess + updated system info          │
       <─────────────────────────────────────────────────
       │
       └─ Repeat [4-8]
```

---

## CONCLUSION

The DockMon v2.2.0 agent system provides:

**Strengths**:
- Clean separation of concerns (config, docker, handlers, protocol)
- Automatic reconnection with exponential backoff
- Comprehensive system information collection
- Rolling update capability with health checks
- Agent self-update mechanism

**Weaknesses**:
- Missing cryptographic verification (checksums, TLS)
- Unencrypted token storage
- No command ACL/authorization
- Incomplete error handling (e.g., slow-read attacks)
- Dead connection detection only reactive

**Recommended Audit Focus**:
1. Implement checksum verification for all downloads
2. Add TLS certificate validation for remote connections
3. Implement agent command ACL based on capabilities
4. Add request/response size limits and timeouts
5. Implement heartbeat from agent to detect dead connections
6. Encrypt persistent token storage
