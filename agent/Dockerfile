# Build stage
FROM golang:1.24-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git ca-certificates

WORKDIR /build

# Copy shared module first (required by go.mod replace directive)
COPY shared/ /shared/

# Copy go mod files
COPY agent/go.mod agent/go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY agent/ .

# Build binary
ARG VERSION=dev
ARG COMMIT=unknown
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" \
    -o dockmon-agent \
    ./cmd/agent

# Runtime stage
FROM alpine:3.19

# Install runtime dependencies (su-exec for dropping privileges)
RUN apk add --no-cache ca-certificates tzdata su-exec

# Create non-root user
RUN addgroup -g 1000 agent && \
    adduser -D -u 1000 -G agent agent

# Create data directory
RUN mkdir -p /data && chown agent:agent /data

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/dockmon-agent /app/dockmon-agent

# Create entrypoint script that fixes permissions then drops to agent user
RUN echo '#!/bin/sh' > /entrypoint.sh && \
    echo 'set -e' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Fix /data permissions if mounted volume has wrong ownership' >> /entrypoint.sh && \
    echo 'if [ -d /data ] && [ "$(stat -c %u /data)" != "1000" ]; then' >> /entrypoint.sh && \
    echo '    echo "Fixing /data permissions (was owned by $(stat -c %U /data))"' >> /entrypoint.sh && \
    echo '    chown -R agent:agent /data' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Drop privileges and run agent' >> /entrypoint.sh && \
    echo 'exec su-exec agent /app/dockmon-agent "$@"' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Data directory at /data - mount a named volume to persist agent identity:
#   -v dockmon-agent-data:/data

# Expose no ports (agent connects outbound only)

ENTRYPOINT ["/entrypoint.sh"]
