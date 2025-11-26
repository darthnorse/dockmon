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

# Install runtime dependencies
RUN apk add --no-cache ca-certificates tzdata

# Create non-root user
RUN addgroup -g 1000 agent && \
    adduser -D -u 1000 -G agent agent

# Create data directory
RUN mkdir -p /data && chown agent:agent /data

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/dockmon-agent /app/dockmon-agent

# Switch to non-root user
USER agent

# Data directory at /data - mount a named volume to persist agent identity:
#   -v agent-data:/data

# Expose no ports (agent connects outbound only)

ENTRYPOINT ["/app/dockmon-agent"]
