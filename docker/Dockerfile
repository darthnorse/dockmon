# DockMon All-in-One Container
# Multi-stage build: Go stats service + Python backend + React frontend

# Stage 1: Build Go services (stats-service and compose-service)
FROM golang:1.24-alpine AS go-builder

WORKDIR /build

# Copy shared module first (needed by both services)
# Place at /build/shared so relative paths ../shared work from service dirs
COPY shared/ /build/shared/

# Build stats-service
WORKDIR /build/stats-service
COPY stats-service/go.mod stats-service/go.sum* ./
RUN go mod download
COPY stats-service/*.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o stats-service .

# Build compose-service
WORKDIR /build/compose-service
COPY compose-service/go.mod compose-service/go.sum* ./
RUN go mod download
COPY compose-service/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o compose-service ./cmd/compose-service/

# Stage 2: Build React frontend
FROM node:20-alpine AS frontend-builder

# Accept BASE_PATH as build argument (defaults to root path)
ARG BASE_PATH=/

WORKDIR /build

# Copy package files
COPY ui/package*.json ./

# Install dependencies
RUN npm ci

# Copy source files
COPY ui/ ./

# Build the React app with BASE_PATH
ENV BASE_PATH=${BASE_PATH}
RUN npm run build

# Stage 3: Final image with Python + Go binary + built React app
FROM python:3.13-alpine

ARG APP_VERSION=dev

# OCI Image labels (https://github.com/opencontainers/image-spec/blob/main/annotations.md)
LABEL org.opencontainers.image.title="DockMon"
LABEL org.opencontainers.image.description="Self-hosted Docker monitoring and management platform with multi-host support, container updates, health checks, and alerts"
LABEL org.opencontainers.image.authors="darthnorse"
LABEL org.opencontainers.image.source="https://github.com/darthnorse/dockmon"
LABEL org.opencontainers.image.url="https://github.com/darthnorse/dockmon"
LABEL org.opencontainers.image.documentation="https://github.com/darthnorse/dockmon"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.vendor="darthnorse"
LABEL org.opencontainers.image.version="${APP_VERSION}"

# Install runtime dependencies and build dependencies (temporarily for Python packages with C extensions)
RUN apk upgrade --no-cache \
    && apk add --no-cache \
    # Runtime dependencies
    nginx \
    curl \
    ca-certificates \
    openssl \
    bash \
    libffi \
    && apk add --no-cache --virtual .build-deps \
    # Build dependencies (will be removed after pip install)
    gcc \
    musl-dev \
    linux-headers \
    libffi-dev \
    openssl-dev \
    python3-dev

# Create app directory
WORKDIR /app

# Copy Go service binaries from builder
COPY --from=go-builder /build/stats-service/stats-service /usr/local/bin/stats-service
COPY --from=go-builder /build/compose-service/compose-service /usr/local/bin/compose-service
RUN chmod +x /usr/local/bin/stats-service /usr/local/bin/compose-service

# Upgrade pip to latest version for security fixes
RUN pip install --no-cache-dir --upgrade pip

# Install supervisor 4.3.0 from PyPI (removes pkg_resources dependency)
RUN pip install --no-cache-dir supervisor==4.3.0

# Copy and install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    # Remove build dependencies to keep image small
    && apk del .build-deps

# Copy backend code
COPY backend/ /app/backend/

# Write build-time version file
RUN echo "${APP_VERSION}" > /app/VERSION

# Copy built React frontend from frontend-builder stage
COPY --from=frontend-builder /build/dist /usr/share/nginx/html/
RUN chmod -R 644 /usr/share/nginx/html/*
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \;

# Create certs directory (certificates will be generated at runtime if not present)
RUN mkdir -p /etc/nginx/certs

# Copy nginx configurations
# Alpine nginx uses /etc/nginx/http.d/ instead of sites-enabled/sites-available
RUN rm -f /etc/nginx/http.d/default.conf
COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/nginx-http.conf /docker/nginx-http.conf

# Add WebSocket upgrade mapping to main nginx.conf (must be in http block)
RUN sed -i '/^http {/a \    # WebSocket upgrade mapping\n    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        '"''"' close;\n    }\n' /etc/nginx/nginx.conf

# Copy supervisor configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create data directory and log directories with correct permissions
RUN mkdir -p /app/data && \
    chmod 700 /app/data && \
    mkdir -p /var/log/supervisor /var/run

# Create startup script
RUN echo '#!/bin/bash' > /startup.sh && \
    echo 'set -e' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Ensure certificates exist (generate if missing)' >> /startup.sh && \
    echo 'if [ ! -f /etc/nginx/certs/dockmon.crt ]; then' >> /startup.sh && \
    echo '  mkdir -p /etc/nginx/certs' >> /startup.sh && \
    echo '  echo "Generating SSL certificates (47-day validity for Apple browser compliance)..."' >> /startup.sh && \
    echo '  openssl req -x509 -nodes -days 47 -newkey rsa:2048 \' >> /startup.sh && \
    echo '    -keyout /etc/nginx/certs/dockmon.key \' >> /startup.sh && \
    echo '    -out /etc/nginx/certs/dockmon.crt \' >> /startup.sh && \
    echo '    -subj "/C=US/ST=State/L=City/O=DockMon/CN=localhost" > /dev/null 2>&1' >> /startup.sh && \
    echo '  echo "SSL certificates generated successfully with 47-day validity"' >> /startup.sh && \
    echo '  chmod 600 /etc/nginx/certs/dockmon.key' >> /startup.sh && \
    echo '  chmod 644 /etc/nginx/certs/dockmon.crt' >> /startup.sh && \
    echo 'fi' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Detect reverse proxy mode' >> /startup.sh && \
    echo 'if [ "$REVERSE_PROXY_MODE" = "true" ]; then' >> /startup.sh && \
    echo '  echo "Reverse proxy mode enabled - nginx will listen on HTTP port 80"' >> /startup.sh && \
    echo '  cp /docker/nginx-http.conf /etc/nginx/http.d/default.conf' >> /startup.sh && \
    echo 'else' >> /startup.sh && \
    echo '  echo "Direct access mode (default) - nginx will listen on HTTPS port 443"' >> /startup.sh && \
    echo 'fi' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Run database migrations' >> /startup.sh && \
    echo 'echo "Running database migrations..."' >> /startup.sh && \
    echo 'cd /app' >> /startup.sh && \
    echo 'python3 backend/migrate.py' >> /startup.sh && \
    echo 'if [ $? -ne 0 ]; then' >> /startup.sh && \
    echo '  echo "ERROR: Database migration failed. Container will not start."' >> /startup.sh && \
    echo '  exit 1' >> /startup.sh && \
    echo 'fi' >> /startup.sh && \
    echo 'echo "Database migrations completed successfully"' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Start supervisor' >> /startup.sh && \
    echo 'exec /usr/local/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf' >> /startup.sh && \
    chmod +x /startup.sh

# Expose ports (8081 is internal for stats service)
# Port 443: HTTPS mode (default), Port 80: HTTP mode (REVERSE_PROXY_MODE=true)
EXPOSE 443 80 8080

# Health check - checks both backend and stats service
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health && curl -f http://localhost:8081/health || exit 1

# Volume for persistent data
VOLUME ["/app/data"]

# Start supervisor
CMD ["/startup.sh"]
