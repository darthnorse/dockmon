"""
Centralized path configuration for DockMon
Ensures all modules use consistent, volume-mounted paths
"""

import os

# Base paths - these MUST use absolute paths to the volume mount
# The /app/data directory is mounted as a volume in Docker
DATA_DIR = os.getenv('DOCKMON_DATA_DIR', '/app/data')

# Database path - MUST be in the volume mount for persistence
DATABASE_PATH = os.path.join(DATA_DIR, 'dockmon.db')
DATABASE_URL = f'sqlite:///{DATABASE_PATH}'

# Credentials file - also in volume for persistence
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'frontend_credentials.txt')

# Certificates directory for TLS
CERTS_DIR = os.path.join(DATA_DIR, 'certs')

# Ensure data directory exists with proper permissions
def ensure_data_dirs():
    """Create data directories if they don't exist"""
    for directory in [DATA_DIR, CERTS_DIR]:
        os.makedirs(directory, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass  # May not have permission in some environments

# For development/testing outside Docker
if not os.path.exists('/app'):
    # Running locally, use relative paths
    DATA_DIR = './data'
    DATABASE_PATH = os.path.join(DATA_DIR, 'dockmon.db')
    DATABASE_URL = f'sqlite:///{DATABASE_PATH}'
    CREDENTIALS_FILE = os.path.join(DATA_DIR, 'frontend_credentials.txt')
    CERTS_DIR = os.path.join(DATA_DIR, 'certs')