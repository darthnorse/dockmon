import os
import shutil
from pathlib import Path

IO_BLOCK = 1024 * 1024


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new_file(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def copy_new_file(src: Path, dst: Path, mode: int = 0o600) -> None:
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with open(src, "rb") as s, os.fdopen(fd, "wb") as d:
        shutil.copyfileobj(s, d, IO_BLOCK)
        d.flush()
        os.fsync(d.fileno())
