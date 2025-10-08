# DockMon All-in-One Container
# Multi-stage build: Go stats service + Python backend + React frontend

# Stage 1: Build Go stats service
FROM golang:1.23-alpine AS go-builder

WORKDIR /build

# Copy go mod files
COPY stats-service/go.mod stats-service/go.sum* ./

# Download dependencies
RUN go mod download

# Copy source code
COPY stats-service/*.go ./

# Build binary (static linking for alpine)
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o stats-service .

# Stage 2: Build React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Copy package files
COPY ui/package*.json ./

# Install dependencies
RUN npm ci

# Copy source files
COPY ui/ ./

# Build the React app
RUN npm run build

# Stage 3: Final image with Python + Go binary + built React app
FROM python:3.11.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    supervisor \
    curl \
    gcc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy Go stats service binary from builder
COPY --from=go-builder /build/stats-service /usr/local/bin/stats-service
RUN chmod +x /usr/local/bin/stats-service

# Copy and install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy built React frontend from frontend-builder stage
COPY --from=frontend-builder /build/dist /usr/share/nginx/html/
RUN chmod -R 644 /usr/share/nginx/html/*
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \;

# Create certs directory (certificates will be generated at runtime if not present)
RUN mkdir -p /etc/nginx/certs

# Copy nginx configuration
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default

# Add WebSocket upgrade mapping to main nginx.conf (must be in http block)
RUN sed -i '/^http {/a \    # WebSocket upgrade mapping\n    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        '"''"' close;\n    }\n' /etc/nginx/nginx.conf

# Copy supervisor configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create data directory with correct permissions
RUN mkdir -p /app/data && \
    chmod 700 /app/data

# Create startup script
RUN echo '#!/bin/bash' > /startup.sh && \
    echo 'set -e' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Ensure certificates exist (generate if missing)' >> /startup.sh && \
    echo 'if [ ! -f /etc/nginx/certs/dockmon.crt ]; then' >> /startup.sh && \
    echo '  mkdir -p /etc/nginx/certs' >> /startup.sh && \
    echo '  echo "Generating SSL certificates..."' >> /startup.sh && \
    echo '  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \' >> /startup.sh && \
    echo '    -keyout /etc/nginx/certs/dockmon.key \' >> /startup.sh && \
    echo '    -out /etc/nginx/certs/dockmon.crt \' >> /startup.sh && \
    echo '    -subj "/C=US/ST=State/L=City/O=DockMon/CN=localhost" > /dev/null 2>&1' >> /startup.sh && \
    echo '  echo "SSL certificates generated successfully"' >> /startup.sh && \
    echo '  chmod 600 /etc/nginx/certs/dockmon.key' >> /startup.sh && \
    echo '  chmod 644 /etc/nginx/certs/dockmon.crt' >> /startup.sh && \
    echo 'fi' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Wait for backend to be ready' >> /startup.sh && \
    echo 'sleep 2' >> /startup.sh && \
    echo '' >> /startup.sh && \
    echo '# Start supervisor' >> /startup.sh && \
    echo 'exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf' >> /startup.sh && \
    chmod +x /startup.sh

# Expose ports (8081 is internal for stats service)
EXPOSE 443 8080

# Health check - checks both backend and stats service
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health && curl -f http://localhost:8081/health || exit 1

# Volume for persistent data
VOLUME ["/app/data"]

# Start supervisor
CMD ["/startup.sh"]
