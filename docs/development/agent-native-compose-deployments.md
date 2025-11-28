# Agent Native Docker Compose Deployments

**Status:** Planning - Ready for Review
**Branch:** `feature/v2.2.0-agent`
**Created:** 2024-11-27
**Target:** v2.2.0 (Agent Beta)

---

## Executive Summary

This document proposes using **native Docker Compose** for deployments on agent-based hosts, rather than the current approach of parsing compose files and creating containers individually via the Docker API.

This follows the same **passthrough philosophy** applied to container updates: instead of reimplementing Docker Compose at a higher level, use the native tool and orchestrate around it.

---

## Problem Statement

### Current Backend-Driven Deployment Approach

Location: `backend/main.py` (deployment routes ~line 2700+)

The current implementation:
1. Receives docker-compose.yml content from user
2. Parses YAML and extracts service definitions
3. Creates networks and volumes via Docker API
4. Creates containers one-by-one via Docker API
5. Starts containers in dependency order

### What's Not Supported

| Feature | Status | Difficulty to Implement |
|---------|--------|------------------------|
| `depends_on` with conditions | Not supported | High |
| `build:` directives | Not supported | Very High |
| `profiles:` | Not supported | Medium |
| `extends:` | Not supported | High |
| `secrets:` / `configs:` | Not supported | Medium |
| Environment variable interpolation | Partial | Medium |
| Multiple compose files | Not supported | Medium |
| Health check conditions | Not supported | High |
| GPU device requests | Manual config | Low |
| Custom network drivers | Not supported | Medium |

### Maintenance Burden

Every new Docker Compose feature requires:
1. Understanding the compose spec
2. Implementing parsing logic
3. Translating to Docker API calls
4. Handling edge cases
5. Testing across Docker/Podman versions

This is unsustainable long-term.

---

## Proposed Solution: Native Compose Passthrough

### Philosophy

> "Instead of reimplementing Docker Compose, use Docker Compose."

Just as the update passthrough preserves ALL container settings by copying structs rather than fields, compose passthrough preserves ALL compose features by running compose natively.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                 │
│  (Compose Editor, Deploy Button, Progress Display)              │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP POST /api/deployments
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Backend                                  │
│  1. Validate compose content (syntax check)                     │
│  2. Store deployment record in database                         │
│  3. Detect host type: agent vs mTLS/local                       │
│  4. Route to appropriate executor                               │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          │                               │
          ▼                               ▼
┌─────────────────────┐       ┌─────────────────────────────────┐
│  mTLS/Local Host    │       │         Agent Host              │
│  (existing code)    │       │  (new: native compose)          │
│                     │       │                                 │
│  - Parse compose    │       │  1. Receive compose content     │
│  - Create via API   │       │  2. Write to temp file          │
│  - Track progress   │       │  3. Run docker compose up -d    │
└─────────────────────┘       │  4. Stream progress events      │
                              │  5. Query container IDs         │
                              │  6. Report completion           │
                              └─────────────────────────────────┘
```

### Benefits

1. **100% Compose Compatibility** - All features work, current and future
2. **Reduced Maintenance** - Docker Compose team maintains the complex logic
3. **User Mental Model** - "Run my compose file" not "parse and recreate"
4. **Debugging** - Standard compose commands work for troubleshooting
5. **Podman Compatibility** - podman-compose or podman compose works similarly

---

## Implementation Plan

### Phase 0: Prerequisites

**Ensure Docker Compose available in agent:**

```dockerfile
# In agent Dockerfile
FROM docker:24-cli AS docker
# docker compose plugin is included in docker:24-cli
# Verify: docker compose version
```

**Agent Requirements:**
- Docker CLI with compose plugin (v2.x)
- OR standalone docker-compose binary
- Fallback detection for podman-compose

### Phase 1: Basic Compose Deployment

**Scope:** Simple compose files without build directives

#### Agent Side (Go)

**New file:** `agent/internal/handlers/deploy.go`

```go
package handlers

// DeployComposeRequest is sent from backend to agent
type DeployComposeRequest struct {
    DeploymentID   string            `json:"deployment_id"`
    ProjectName    string            `json:"project_name"`
    ComposeContent string            `json:"compose_content"`
    Environment    map[string]string `json:"environment,omitempty"`
    Action         string            `json:"action"` // "up", "down", "restart"
}

// DeployComposeResult is sent from agent to backend on completion
type DeployComposeResult struct {
    DeploymentID string                    `json:"deployment_id"`
    Success      bool                      `json:"success"`
    Services     map[string]ServiceResult  `json:"services"`
    Error        string                    `json:"error,omitempty"`
}

// ServiceResult contains info about a deployed service
type ServiceResult struct {
    ContainerID   string `json:"container_id"`   // 12-char short ID
    ContainerName string `json:"container_name"`
    Image         string `json:"image"`
    Status        string `json:"status"`         // "running", "created", "failed"
    Error         string `json:"error,omitempty"`
}

// DeployHandler manages compose deployments
type DeployHandler struct {
    dockerClient *docker.Client
    log          *logrus.Logger
    sendEvent    func(string, interface{}) error
    composeCmd   string // "docker compose" or "docker-compose" or "podman-compose"
}
```

**Key Methods:**

```go
// NewDeployHandler creates handler and detects compose command
func NewDeployHandler(ctx context.Context, ...) (*DeployHandler, error) {
    // Detect available compose command
    composeCmd := detectComposeCommand()
    // ...
}

// DeployCompose handles the deploy_compose command
func (h *DeployHandler) DeployCompose(ctx context.Context, req DeployComposeRequest) (*DeployComposeResult, error) {
    // 1. Write compose content to temp file
    // 2. Set environment variables
    // 3. Run compose up/down based on action
    // 4. Parse output for progress
    // 5. Query container IDs on success
    // 6. Report result
}

// detectComposeCommand finds available compose command
func detectComposeCommand() string {
    // Try in order:
    // 1. "docker compose" (v2 plugin)
    // 2. "docker-compose" (standalone v1/v2)
    // 3. "podman-compose" (Podman)
}
```

**Progress Events:**

```go
// Sent during compose up
type DeployProgressEvent struct {
    DeploymentID string `json:"deployment_id"`
    Stage        string `json:"stage"`    // "pulling", "creating", "starting"
    Service      string `json:"service"`  // Which service
    Message      string `json:"message"`
    Progress     int    `json:"progress"` // 0-100
}
```

#### Backend Side (Python)

**New file:** `backend/deployments/agent_executor.py`

```python
"""
Agent-based deployment executor using native Docker Compose.

Routes deployment requests to agent and handles progress/completion events.
"""

class AgentDeploymentExecutor:
    """Executes deployments via agent using native docker compose."""

    async def deploy(
        self,
        host_id: str,
        deployment_id: str,
        compose_content: str,
        project_name: str,
        environment: dict[str, str] | None = None,
    ) -> bool:
        """
        Deploy via agent using native compose.

        1. Send deploy_compose command to agent
        2. Wait for progress events (forward to UI)
        3. Wait for completion event
        4. Update database with container IDs
        """

    async def teardown(
        self,
        host_id: str,
        deployment_id: str,
        project_name: str,
    ) -> bool:
        """
        Teardown deployment via agent using compose down.
        """
```

**Routing Logic (in deployment router):**

```python
async def execute_deployment(self, deployment: Deployment, host: Host) -> bool:
    # Detect host type and route appropriately
    if host.connection_type == "agent":
        # Use native compose via agent
        return await self.agent_executor.deploy(
            host_id=host.id,
            deployment_id=deployment.id,
            compose_content=deployment.compose_content,
            project_name=deployment.name,
            environment=deployment.environment,
        )
    else:
        # Use existing backend-driven approach
        return await self.docker_executor.deploy(...)
```

#### WebSocket Handler Updates

**In `backend/agent/websocket_handler.py`:**

```python
# Add new event types
elif event_type == "deploy_progress":
    await self._handle_deploy_progress(payload)

elif event_type == "deploy_complete":
    await self._handle_deploy_complete(payload)
```

#### Database Updates

No schema changes needed. Existing tables work:

- `deployments` - Stores compose content, project name, status
- `deployment_metadata` - Links deployment to containers
- `containers` - Container records (created from agent's ServiceResult)

### Phase 2: Enhanced Features

**Scope:** Environment variables, error handling, partial failure recovery

#### Environment Variable Passing

```go
type DeployComposeRequest struct {
    // ... existing fields
    Environment map[string]string `json:"environment"`
}

func (h *DeployHandler) DeployCompose(...) {
    // Set environment before running compose
    for key, value := range req.Environment {
        os.Setenv(key, value)
    }
    defer func() {
        for key := range req.Environment {
            os.Unsetenv(key)
        }
    }()
    // ...
}
```

#### Partial Failure Handling

```go
// If some services fail, report which succeeded
type DeployComposeResult struct {
    Success         bool                   `json:"success"`
    PartialSuccess  bool                   `json:"partial_success"`
    Services        map[string]ServiceResult `json:"services"`
    FailedServices  []string               `json:"failed_services,omitempty"`
}

// On partial failure:
// 1. Report which services succeeded/failed
// 2. Keep successful containers running (user can fix and retry)
// 3. Or offer compose down to clean up
```

#### Compose Down for Cleanup

```go
func (h *DeployHandler) TeardownCompose(ctx context.Context, req DeployComposeRequest) error {
    // docker compose -f <file> -p <project> down --volumes --remove-orphans
}
```

### Phase 3: Advanced Features

**Scope:** Build support, multi-file compose, profiles

#### Build Support (Requires Build Context)

For `build:` directives, we need the build context (Dockerfile, source files):

**Option A: Pre-built images only**
- Reject compose files with `build:` directives
- Require users to push images to registry first

**Option B: Build context transfer**
- User uploads build context as tar archive
- Agent extracts and builds
- More complex, higher bandwidth

**Recommendation:** Start with Option A, add Option B later if needed.

#### Multi-File Compose

```go
type DeployComposeRequest struct {
    // Support multiple compose files
    ComposeFiles []ComposeFile `json:"compose_files"`
}

type ComposeFile struct {
    Name    string `json:"name"`    // "docker-compose.yml", "docker-compose.prod.yml"
    Content string `json:"content"`
}

// Run: docker compose -f file1.yml -f file2.yml up -d
```

#### Profiles Support

```go
type DeployComposeRequest struct {
    // ... existing fields
    Profiles []string `json:"profiles,omitempty"` // ["production", "monitoring"]
}

// Run: docker compose --profile production --profile monitoring up -d
```

---

## Progress Reporting

### Parsing Compose Output

Docker Compose v2 supports `--progress` flag:

```bash
docker compose up -d --progress=plain
```

Output format:
```
 ✔ Network myapp_default  Created
 ✔ Volume myapp_data      Created
 ✔ Container myapp-db-1   Started
 ✔ Container myapp-web-1  Started
```

For more detailed progress (image pulls):
```bash
docker compose pull --progress=plain
docker compose up -d --no-pull
```

### Progress Event Flow

```
Agent                           Backend                         Frontend
  │                                │                                │
  │ deploy_progress                │                                │
  │ {stage: "pulling",             │                                │
  │  service: "db",                │                                │
  │  message: "Pulling postgres"}  │                                │
  │ ──────────────────────────────>│                                │
  │                                │ WebSocket broadcast            │
  │                                │ ──────────────────────────────>│
  │                                │                                │ Update UI
  │                                │                                │
  │ deploy_progress                │                                │
  │ {stage: "creating",            │                                │
  │  service: "db"}                │                                │
  │ ──────────────────────────────>│                                │
  │                                │                                │
  │ deploy_progress                │                                │
  │ {stage: "starting",            │                                │
  │  service: "web"}               │                                │
  │ ──────────────────────────────>│                                │
  │                                │                                │
  │ deploy_complete                │                                │
  │ {success: true,                │                                │
  │  services: {...}}              │                                │
  │ ──────────────────────────────>│                                │
  │                                │ Update database                │
  │                                │ WebSocket broadcast            │
  │                                │ ──────────────────────────────>│
  │                                │                                │ Show success
```

---

## Container Discovery

After `docker compose up`, we need to discover container IDs for database records:

```go
func (h *DeployHandler) discoverContainers(ctx context.Context, projectName string) (map[string]ServiceResult, error) {
    // Option 1: docker compose ps --format json
    cmd := exec.CommandContext(ctx, "docker", "compose", "-p", projectName, "ps", "--format", "json")

    // Option 2: docker ps with label filter
    // Compose adds labels: com.docker.compose.project=<name>
    containers, _ := h.dockerClient.ListAllContainers(ctx)
    for _, c := range containers {
        if c.Labels["com.docker.compose.project"] == projectName {
            serviceName := c.Labels["com.docker.compose.service"]
            // ...
        }
    }
}
```

---

## Error Handling

### Compose Command Failures

```go
func (h *DeployHandler) runCompose(ctx context.Context, args ...string) (string, error) {
    cmd := exec.CommandContext(ctx, h.composeCmd, args...)

    var stdout, stderr bytes.Buffer
    cmd.Stdout = &stdout
    cmd.Stderr = &stderr

    err := cmd.Run()
    if err != nil {
        // Parse stderr for meaningful error
        return "", fmt.Errorf("compose failed: %s", parseComposeError(stderr.String()))
    }

    return stdout.String(), nil
}

func parseComposeError(stderr string) string {
    // Extract meaningful error message from compose output
    // Examples:
    // - "no such image: myapp:latest"
    // - "port is already allocated"
    // - "network not found"
}
```

### Rollback Strategy

On deployment failure:

```go
func (h *DeployHandler) DeployCompose(...) (*DeployComposeResult, error) {
    // ...

    if err := h.runComposeUp(ctx, ...); err != nil {
        // Attempt cleanup
        h.log.Warn("Deployment failed, cleaning up...")

        // Run compose down to remove partial deployment
        if cleanupErr := h.runComposeDown(ctx, ...); cleanupErr != nil {
            h.log.WithError(cleanupErr).Error("Cleanup failed")
        }

        return &DeployComposeResult{
            Success: false,
            Error:   err.Error(),
        }, nil
    }
    // ...
}
```

---

## Security Considerations

### Compose File Content

The compose file may contain sensitive data:
- Database passwords in environment variables
- API keys
- Secret references

**Mitigations:**
1. WebSocket connection already authenticated and encrypted (TLS)
2. Temp file written with restrictive permissions (0600)
3. Temp file deleted after deployment completes
4. Environment variables not logged

```go
func (h *DeployHandler) writeComposeFile(content string) (string, error) {
    f, err := os.CreateTemp("", "dockmon-compose-*.yml")
    if err != nil {
        return "", err
    }

    // Restrictive permissions
    if err := f.Chmod(0600); err != nil {
        os.Remove(f.Name())
        return "", err
    }

    if _, err := f.WriteString(content); err != nil {
        os.Remove(f.Name())
        return "", err
    }

    return f.Name(), f.Close()
}

// Cleanup in defer
defer os.Remove(composeFile)
```

### Command Injection Prevention

Never interpolate user input into shell commands:

```go
// WRONG - vulnerable to injection
cmd := exec.Command("sh", "-c", fmt.Sprintf("docker compose -p %s up", projectName))

// CORRECT - arguments passed safely
cmd := exec.Command("docker", "compose", "-p", projectName, "up", "-d")
```

---

## Testing Strategy

### Unit Tests

```go
func TestDeployHandler_ParseComposeOutput(t *testing.T) {
    // Test parsing of compose progress output
}

func TestDeployHandler_DiscoverContainers(t *testing.T) {
    // Test container discovery with mock docker client
}

func TestDeployHandler_ErrorParsing(t *testing.T) {
    // Test error message extraction from compose stderr
}
```

### Integration Tests

```go
func TestDeployCompose_SimpleService(t *testing.T) {
    // Deploy nginx via compose, verify container created
}

func TestDeployCompose_MultiService(t *testing.T) {
    // Deploy web + db, verify both containers, verify networking
}

func TestDeployCompose_Failure(t *testing.T) {
    // Deploy with invalid image, verify cleanup
}
```

### Backend Tests

```python
async def test_agent_deployment_routing():
    """Verify agent hosts route to compose executor."""

async def test_agent_deployment_progress():
    """Verify progress events forwarded to UI."""

async def test_agent_deployment_database_update():
    """Verify container records created from ServiceResult."""
```

---

## Migration Path

### Existing Deployments

Deployments created with the backend-driven approach continue to work:
- Backend still has the parsing/creation code
- Only new deployments on agent hosts use native compose
- No migration needed for existing deployments

### Feature Flag (Optional)

```python
# In settings or environment
AGENT_NATIVE_COMPOSE = True  # Default True in v2.2.0

# In deployment router
if host.connection_type == "agent" and settings.AGENT_NATIVE_COMPOSE:
    return await self.agent_executor.deploy(...)
else:
    return await self.docker_executor.deploy(...)
```

---

## Timeline

### Phase 1 (MVP)
- [ ] Agent: Detect compose command availability
- [ ] Agent: Implement deploy_compose handler (up/down)
- [ ] Agent: Implement progress event streaming
- [ ] Agent: Implement container discovery
- [ ] Backend: Add AgentDeploymentExecutor
- [ ] Backend: Add WebSocket handlers for deploy events
- [ ] Backend: Route agent hosts to compose executor
- [ ] Tests: Basic deployment tests

### Phase 2 (Enhanced)
- [ ] Environment variable passing
- [ ] Partial failure handling
- [ ] Improved error messages
- [ ] Compose down for cleanup

### Phase 3 (Advanced)
- [ ] Profile support
- [ ] Multi-file compose support
- [ ] Build support investigation

---

## Open Questions

1. **Build context:** How do we handle compose files with `build:` directives?
   - Option A: Reject and require pre-built images
   - Option B: Implement build context transfer (complex)

2. **Secrets management:** Should we support Docker secrets/configs?
   - These require swarm mode, may not be relevant

3. **Compose version detection:** How to handle compose v1 vs v2?
   - v2 is standard now, v1 deprecated
   - Agent should require v2 (docker compose plugin)

4. **Podman-compose compatibility:** How well does podman-compose match docker compose?
   - Test coverage needed for Podman deployments

---

## References

- [Docker Compose Specification](https://docs.docker.com/compose/compose-file/)
- [Docker Compose CLI Reference](https://docs.docker.com/compose/reference/)
- [Agent Update Passthrough Refactor](./agent-update-passthrough-refactor.md)
- [Existing Deployment Code](../../backend/main.py) (line ~2700+)
