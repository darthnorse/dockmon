"""One backup/restore operation at a time, across the API and the CLI.

flock locks belong to the open file description, so two opens in one process
(two request threads) exclude each other, and the lock is held by whichever
thread does the work: cancelling the request that awaits it cannot release it
early.
"""

import fcntl
import os
import time
from contextlib import contextmanager

from backup.errors import BackupBusyError
from backup.paths import BackupPaths

LOCK_NAME = "operation.lock"


def _open_lock_file(paths: BackupPaths) -> int:
    paths.restore_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.open(paths.restore_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)


LOCK_ATTEMPTS = 5
LOCK_RETRY_SECONDS = 0.02


@contextmanager
def operation_lock(paths: BackupPaths, attempts: int = LOCK_ATTEMPTS):
    """A few quick retries ride out an is_busy() probe that holds the lock for an instant."""
    fd = _open_lock_file(paths)
    try:
        for attempt in range(attempts):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == attempts - 1:
                    raise BackupBusyError("Another backup or restore operation is running") from None
                time.sleep(LOCK_RETRY_SECONDS)
        yield
    finally:
        os.close(fd)


def is_busy(paths: BackupPaths) -> bool:
    try:
        with operation_lock(paths, attempts=1):
            return False
    except BackupBusyError:
        return True
