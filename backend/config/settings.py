"""
Configuration Management for DockMon
Centralizes all environment-based configuration and settings
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional


class HealthCheckFilter(logging.Filter):
    """Filter out health check and routine polling requests to reduce log noise"""
    def filter(self, record: logging.LogRecord) -> bool:
        # Filter out successful requests to these endpoints
        # Check both the formatted message and the raw args
        message = record.getMessage()

        # For uvicorn access logs, the message format is:
        # 'IP:PORT - "METHOD /path HTTP/1.1" STATUS'
        if '200 OK' in message or '200' in str(getattr(record, 'args', '')):
            # Health checks
            if '/health' in message:
                return False
            # Container polling (happens every 2 seconds)
            if '/api/containers' in message:
                return False
            # Host polling
            if '/api/hosts' in message:
                return False
            # Alert counts polling (happens every 30 seconds)
            if '/api/alerts/' in message and 'state=open' in message:
                return False
        return True


def setup_logging():
    """Configure application logging with rotation"""
    from .paths import DATA_DIR

    # Create logs directory with secure permissions
    log_dir = os.path.join(DATA_DIR, 'logs')
    os.makedirs(log_dir, mode=0o700, exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()

    # Close and clear any existing handlers (e.g., from Alembic migrations or other libraries)
    # to ensure our logging configuration is used and prevent file descriptor leaks
    for handler in root_logger.handlers[:]:  # Copy list to avoid modification during iteration
        handler.close()
        root_logger.removeHandler(handler)

    root_logger.setLevel(logging.INFO)

    # Console handler for stdout
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # File handler with rotation for application logs
    # Max 10MB per file, keep 14 backups
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'dockmon.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=14,  # Keep 14 old files
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(console_formatter)

    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Suppress noisy Uvicorn access logs for health checks and polling
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(HealthCheckFilter())


def _is_docker_container_id(hostname: str) -> bool:
    """Check if hostname looks like a Docker container ID"""
    if len(hostname) == 64 or len(hostname) == 12:
        try:
            int(hostname, 16)  # Check if it's hexadecimal
            return True
        except ValueError:
            pass
    return False


def get_cors_origins() -> Optional[str]:
    """
    Get CORS origins from environment or return regex to allow all.

    When DOCKMON_CORS_ORIGINS is empty, returns regex pattern to allow all origins.
    This makes DockMon production-ready out of the box while still requiring
    authentication for all endpoints.

    Returns:
        - Comma-separated string of specific origins if DOCKMON_CORS_ORIGINS is set
        - None to use regex pattern (allow all) if empty
    """
    # Check for custom origins from environment
    custom_origins = os.getenv('DOCKMON_CORS_ORIGINS')
    if custom_origins:
        return custom_origins  # Return as comma-separated string

    # Empty/not set = allow all origins via regex (auth still required for all endpoints)
    return None


class RateLimitConfig:
    """Rate limiting configuration from environment variables"""

    @staticmethod
    def get_limits() -> dict:
        """Get all rate limiting configuration from environment"""
        return {
            # endpoint_pattern: (requests_per_minute, burst_limit, violation_threshold)
            "default": (
                int(os.getenv('DOCKMON_RATE_LIMIT_DEFAULT', 120)),
                int(os.getenv('DOCKMON_RATE_BURST_DEFAULT', 20)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_DEFAULT', 8))
            ),
            "auth": (
                int(os.getenv('DOCKMON_RATE_LIMIT_AUTH', 60)),
                int(os.getenv('DOCKMON_RATE_BURST_AUTH', 15)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_AUTH', 5))
            ),
            "hosts": (
                int(os.getenv('DOCKMON_RATE_LIMIT_HOSTS', 60)),
                int(os.getenv('DOCKMON_RATE_BURST_HOSTS', 15)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_HOSTS', 8))
            ),
            "containers": (
                int(os.getenv('DOCKMON_RATE_LIMIT_CONTAINERS', 200)),
                int(os.getenv('DOCKMON_RATE_BURST_CONTAINERS', 40)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_CONTAINERS', 15))
            ),
            "notifications": (
                int(os.getenv('DOCKMON_RATE_LIMIT_NOTIFICATIONS', 30)),
                int(os.getenv('DOCKMON_RATE_BURST_NOTIFICATIONS', 10)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_NOTIFICATIONS', 5))
            ),
        }


class AppConfig:
    """Main application configuration"""

    # Server settings
    HOST = os.getenv('DOCKMON_HOST', '0.0.0.0')
    PORT = int(os.getenv('DOCKMON_PORT', 8080))

    # Security settings
    CORS_ORIGINS = get_cors_origins()

    # Import centralized paths
    from .paths import DATABASE_URL as DEFAULT_DATABASE_URL, CREDENTIALS_FILE as DEFAULT_CREDENTIALS_FILE

    # Database settings
    DATABASE_URL = os.getenv('DOCKMON_DATABASE_URL', DEFAULT_DATABASE_URL)

    # Logging
    LOG_LEVEL = os.getenv('DOCKMON_LOG_LEVEL', 'INFO')

    # Authentication
    CREDENTIALS_FILE = os.getenv('DOCKMON_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE)
    SESSION_TIMEOUT_HOURS = int(os.getenv('DOCKMON_SESSION_TIMEOUT_HOURS', 24))

    # Rate limiting
    RATE_LIMITS = RateLimitConfig.get_limits()

    @classmethod
    def validate(cls):
        """Validate configuration"""
        if cls.PORT < 1 or cls.PORT > 65535:
            raise ValueError(f"Invalid port: {cls.PORT}")

        if cls.SESSION_TIMEOUT_HOURS < 1:
            raise ValueError(f"Session timeout must be at least 1 hour: {cls.SESSION_TIMEOUT_HOURS}")

        return True