# DockMon All-in-One Container
# Combines both frontend and backend in a single container using supervisor

FROM python:3.11.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    supervisor \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy and install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy frontend files
COPY src/index.html /usr/share/nginx/html/index.html
COPY src/login.html /usr/share/nginx/html/login.html
COPY src/favicon.ico /usr/share/nginx/html/favicon.ico
COPY src/lucide.min.js /usr/share/nginx/html/lucide.min.js
COPY src/images/ /usr/share/nginx/html/images/
RUN chmod 644 /usr/share/nginx/html/*.html /usr/share/nginx/html/*.ico /usr/share/nginx/html/*.js

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
    echo '  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \' >> /startup.sh && \
    echo '    -keyout /etc/nginx/certs/dockmon.key \' >> /startup.sh && \
    echo '    -out /etc/nginx/certs/dockmon.crt \' >> /startup.sh && \
    echo '    -subj "/C=US/ST=State/L=City/O=DockMon/CN=localhost"' >> /startup.sh && \
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

# Expose ports
EXPOSE 443 8080

# Health check - checks backend directly since nginx HTTPS requires cert
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Volume for persistent data
VOLUME ["/app/data"]

# Start supervisor
CMD ["/startup.sh"]