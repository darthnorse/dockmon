import os

_VERSION_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'VERSION')


def get_app_version() -> str:
    try:
        with open(_VERSION_FILE) as f:
            version = f.read().strip()
        return version.removeprefix('v') if version else 'dev'
    except OSError:
        return 'dev'
