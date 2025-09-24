# DockMon Backend Dockerfile
# Using pinned SHA256 to avoid Docker Hub registry issues
FROM python:3.11-slim@sha256:2ec5a4a5c3e919570f57675471f081d6299668d909feabd8d4803c6c61af666c

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY . .

# Create data directory for database
RUN mkdir -p /app/data

# Create non-root user
RUN useradd --create-home --shell /bin/bash dockmon
RUN chown -R dockmon:dockmon /app
USER dockmon

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/settings || exit 1

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]