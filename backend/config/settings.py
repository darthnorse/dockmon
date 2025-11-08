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
            if '/api/alerts/' in message:
                return False
            # Update summary polling (happens every 30 seconds)
            if '/api/updates/summary' in message:
                return False
            # Settings polling (frontend polls for theme, etc.)
            if '/api/settings' in message:
                return False
            # User preferences polling (React Query polls for preferences)
            if '/api/v2/user/preferences' in message:
                return False
            # Auto-update configs polling (dashboard polls for each container)
            if '/api/auto-update-configs' in message:
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

    # Get log level from environment variable with validation
    log_level_str = os.getenv('DOCKMON_LOG_LEVEL', 'INFO').upper()
    allowed_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if log_level_str not in allowed_levels:
        print(f"WARNING: Invalid DOCKMON_LOG_LEVEL '{log_level_str}'. Using INFO. Valid values: {allowed_levels}")
        log_level_str = 'INFO'

    log_level = getattr(logging, log_level_str)
    root_logger.setLevel(log_level)

    # Console handler for stdout
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
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
    file_handler.setLevel(log_level)
    file_handler.setFormatter(console_formatter)

    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Suppress noisy Uvicorn access logs for health checks and polling
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(HealthCheckFilter())

    # Suppress httpx client logging (used for health checks and notifications)
    # Only show WARNING and above to avoid logging every HTTP request
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.WARNING)


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


def _safe_int(env_var: str, default: int, min_val: int = None, max_val: int = None) -> int:
    """
    Safely parse an integer from environment variable with validation.

    Args:
        env_var: Environment variable name
        default: Default value if not set
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)

    Returns:
        Parsed and validated integer

    Raises:
        ValueError: If value is not a valid integer or out of range
    """
    value_str = os.getenv(env_var)
    if value_str is None:
        return default

    try:
        value = int(value_str)
    except ValueError:
        raise ValueError(
            f"{env_var} must be a valid integer, got: '{value_str}'"
        )

    if min_val is not None and value < min_val:
        raise ValueError(
            f"{env_var} must be at least {min_val}, got: {value}"
        )

    if max_val is not None and value > max_val:
        raise ValueError(
            f"{env_var} must be at most {max_val}, got: {value}"
        )

    return value


class RateLimitConfig:
    """Rate limiting configuration from environment variables"""

    @staticmethod
    def get_limits() -> dict:
        """
        Get all rate limiting configuration from environment.

        Rate limits are validated to be positive integers between 1 and 10000.
        """
        return {
            # endpoint_pattern: (requests_per_minute, burst_limit, violation_threshold)
            "default": (
                _safe_int('DOCKMON_RATE_LIMIT_DEFAULT', 120, min_val=1, max_val=10000),
                _safe_int('DOCKMON_RATE_BURST_DEFAULT', 20, min_val=1, max_val=1000),
                _safe_int('DOCKMON_RATE_VIOLATIONS_DEFAULT', 8, min_val=1, max_val=100)
            ),
            "auth": (
                _safe_int('DOCKMON_RATE_LIMIT_AUTH', 60, min_val=1, max_val=10000),
                _safe_int('DOCKMON_RATE_BURST_AUTH', 15, min_val=1, max_val=1000),
                _safe_int('DOCKMON_RATE_VIOLATIONS_AUTH', 5, min_val=1, max_val=100)
            ),
            "hosts": (
                _safe_int('DOCKMON_RATE_LIMIT_HOSTS', 60, min_val=1, max_val=10000),
                _safe_int('DOCKMON_RATE_BURST_HOSTS', 15, min_val=1, max_val=1000),
                _safe_int('DOCKMON_RATE_VIOLATIONS_HOSTS', 8, min_val=1, max_val=100)
            ),
            "containers": (
                _safe_int('DOCKMON_RATE_LIMIT_CONTAINERS', 200, min_val=1, max_val=10000),
                _safe_int('DOCKMON_RATE_BURST_CONTAINERS', 40, min_val=1, max_val=1000),
                _safe_int('DOCKMON_RATE_VIOLATIONS_CONTAINERS', 15, min_val=1, max_val=100)
            ),
            "notifications": (
                _safe_int('DOCKMON_RATE_LIMIT_NOTIFICATIONS', 30, min_val=1, max_val=10000),
                _safe_int('DOCKMON_RATE_BURST_NOTIFICATIONS', 10, min_val=1, max_val=1000),
                _safe_int('DOCKMON_RATE_VIOLATIONS_NOTIFICATIONS', 5, min_val=1, max_val=100)
            ),
        }


class AppConfig:
    """Main application configuration"""

    # Server settings
    HOST = os.getenv('DOCKMON_HOST', '0.0.0.0')
    PORT = _safe_int('DOCKMON_PORT', 8080, min_val=1, max_val=65535)

    # Security settings
    CORS_ORIGINS = get_cors_origins()
    REVERSE_PROXY_MODE = os.getenv('REVERSE_PROXY_MODE', 'false').lower() == 'true'

    # Import centralized paths
    from .paths import DATABASE_URL as DEFAULT_DATABASE_URL, CREDENTIALS_FILE as DEFAULT_CREDENTIALS_FILE

    # Database settings
    DATABASE_URL = os.getenv('DOCKMON_DATABASE_URL', DEFAULT_DATABASE_URL)

    # Logging
    LOG_LEVEL = os.getenv('DOCKMON_LOG_LEVEL', 'INFO').upper()

    # Authentication
    CREDENTIALS_FILE = os.getenv('DOCKMON_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE)
    SESSION_TIMEOUT_HOURS = _safe_int('DOCKMON_SESSION_TIMEOUT_HOURS', 24, min_val=1, max_val=8760)  # Max 1 year

    # Rate limiting
    RATE_LIMITS = RateLimitConfig.get_limits()

    @classmethod
    def validate(cls):
        """
        Validate configuration.

        Note: Most validation now happens during config loading via _safe_int().
        This method provides additional checks for complex validation rules.
        """
        # Validate LOG_LEVEL
        allowed_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if cls.LOG_LEVEL not in allowed_levels:
            raise ValueError(
                f"Invalid DOCKMON_LOG_LEVEL: '{cls.LOG_LEVEL}'. "
                f"Must be one of {allowed_levels}"
            )

        # PORT and SESSION_TIMEOUT_HOURS already validated by _safe_int()

        return True