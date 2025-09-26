"""
Configuration Management for DockMon
Centralizes all environment-based configuration and settings
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from typing import List


def setup_logging():
    """Configure application logging with rotation"""
    from .paths import DATA_DIR

    # Create logs directory with secure permissions
    log_dir = os.path.join(DATA_DIR, 'logs')
    os.makedirs(log_dir, mode=0o700, exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()
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


def _is_docker_container_id(hostname: str) -> bool:
    """Check if hostname looks like a Docker container ID"""
    if len(hostname) == 64 or len(hostname) == 12:
        try:
            int(hostname, 16)  # Check if it's hexadecimal
            return True
        except ValueError:
            pass
    return False


def get_cors_origins() -> List[str]:
    """Get CORS origins from environment or use defaults"""
    # Check for custom origins from environment
    custom_origins = os.getenv('DOCKMON_CORS_ORIGINS')
    if custom_origins:
        return [origin.strip() for origin in custom_origins.split(',')]

    # Default origins for development and common deployment scenarios
    default_origins = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:8081",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081"
    ]

    # Auto-detect common production patterns (but skip Docker container IDs)
    hostname = os.getenv('HOSTNAME', 'localhost')
    if hostname != 'localhost' and not _is_docker_container_id(hostname):
        default_origins.extend([
            f"http://{hostname}:3000",
            f"http://{hostname}:8080",
            f"https://{hostname}:3000",
            f"https://{hostname}:8080"
        ])

    return default_origins


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