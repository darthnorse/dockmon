import threading

import pytest

from backup.errors import BackupBusyError
from backup.oplock import is_busy, operation_lock


def test_second_holder_is_refused(install):
    with operation_lock(install):
        assert is_busy(install)
        with pytest.raises(BackupBusyError):
            with operation_lock(install):
                pass
    assert not is_busy(install)


def test_lock_is_released_when_the_body_raises(install):
    with pytest.raises(RuntimeError):
        with operation_lock(install):
            raise RuntimeError("boom")
    with operation_lock(install):
        pass


def test_lock_excludes_other_threads(install):
    held = threading.Event()
    release = threading.Event()

    def holder():
        with operation_lock(install):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    try:
        with pytest.raises(BackupBusyError):
            with operation_lock(install):
                pass
    finally:
        release.set()
        thread.join(5)
    assert not is_busy(install)
