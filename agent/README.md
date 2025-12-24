# DockMon Agent

The DockMon Agent is a lightweight Go-based agent that connects remote Docker hosts to your DockMon instance via WebSocket. It eliminates the need to expose Docker daemon ports or configure mTLS certificates.

## Features

- **Secure outbound-only connections** - Agent connects to DockMon, no inbound ports required
- **Full container management** - Start, stop, restart, delete, update containers
- **Real-time event streaming** - Container lifecycle events streamed to DockMon
- **Automatic reconnection** - Exponential backoff reconnection (1s → 60s)
- **Self-update capability** - Agent can update itself remotely
- **Multi-architecture support** - amd64 and arm64

## Quick Start

### Prerequisites

- Docker installed on the remote host
- Network connectivity to your DockMon instance
- Registration token from DockMon

### Installation

1. Get a registration token from DockMon UI (Settings → Hosts → Add Host → Agent)

2. Run the agent container:

```bash
docker run -d \
  --name dockmon-agent \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v dockmon-agent-data:/data \
  -e DOCKMON_URL=wss://your-dockmon-instance.com \
  -e REGISTRATION_TOKEN=your-token-here \
  ghcr.io/darthnorse/dockmon-agent:2.2.0
```

**Important**: The `-v dockmon-agent-data:/data` named volume is **required** for:
- Persisting the permanent authentication token across restarts
- Enabling remote self-update functionality (agent updates itself in-place)

Do **not** use bind mounts or omit this volume, as it will break agent persistence and self-update.

3. The agent will automatically register with DockMon and appear in your hosts list

## Configuration

Configuration is done via environment variables:

### Required

- `DOCKMON_URL` - WebSocket URL of your DockMon instance (wss://...)
- `REGISTRATION_TOKEN` - One-time registration token from DockMon (only for first run)
- `PERMANENT_TOKEN` - Permanent token (used after first registration)

### Optional

- `DOCKER_HOST` - Docker socket path (default: `unix:///var/run/docker.sock`)
- `DOCKER_CERT_PATH` - Path to Docker TLS certificates (if using TLS)
- `DOCKER_TLS_VERIFY` - Enable Docker TLS verification (default: `false`)
- `RECONNECT_INITIAL` - Initial reconnection delay (default: `1s`)
- `RECONNECT_MAX` - Maximum reconnection delay (default: `60s`)
- `LOG_LEVEL` - Log level: debug, info, warn, error (default: `info`)
- `LOG_JSON` - Output logs as JSON (default: `true`)

## Architecture

The agent consists of several key components:

- **WebSocket Client** - Maintains connection to DockMon with auto-reconnect
- **Docker Client** - Wraps Docker API for container operations
- **Protocol Handler** - Encodes/decodes WebSocket messages
- **Event Streamer** - Streams Docker events to DockMon
- **Update Handler** - Manages agent self-updates

## Development

### Building locally

```bash
cd agent
go mod download
go build -o dockmon-agent ./cmd/agent
```

### Running locally

```bash
export DOCKMON_URL=ws://localhost:8000
export REGISTRATION_TOKEN=your-token
export LOG_LEVEL=debug
export LOG_JSON=false

./dockmon-agent
```

### Building Docker image

```bash
docker build -t dockmon-agent:dev \
  --build-arg VERSION=dev \
  --build-arg COMMIT=$(git rev-parse --short HEAD) \
  .
```

## Security Considerations

- Agent runs as non-root user (uid 1000)
- Only outbound WebSocket connections (no exposed ports)
- TLS required for production deployments
- Docker socket access required (inherent security consideration)
- Registration token is one-time use
- Permanent token stored in `/data` volume (should be protected)
- Self-update mechanism validates images and maintains container ID stability
- Updates are initiated via authenticated WebSocket commands from DockMon

## Troubleshooting

### Agent won't connect

1. Check `DOCKMON_URL` is correct (wss:// for HTTPS, ws:// for HTTP)
2. Verify network connectivity: `curl -v <DOCKMON_URL>`
3. Check registration token is valid
4. Review agent logs: `docker logs dockmon-agent`

### Container operations fail

1. Verify Docker socket is mounted: `docker exec dockmon-agent ls -l /var/run/docker.sock`
2. Check agent has Docker socket permissions
3. Review DockMon backend logs for errors

### Agent disconnects frequently

1. Check network stability
2. Review reconnection logs
3. Verify DockMon is running and healthy
4. Check for firewall/proxy interference

## Version History

- **2.2.0** - Initial release
  - WebSocket communication
  - Container operations (start, stop, restart, delete, update)
  - Event streaming
  - Self-update capability
  - Multi-architecture support

## License

Same as DockMon main project
