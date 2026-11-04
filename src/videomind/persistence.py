"""Atomic local records and a process lock for a single batch directory."""

import json
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from videomind.errors import ConfigurationError


def atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, data: object) -> None:
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


@contextmanager
def directory_lock(directory: Path) -> Iterator[None]:
    # The OS releases the lock on crash; the persistent file is not a stale lock.
    path = directory / ".batch.lock"
    if path.is_symlink():
        raise ConfigurationError("批次锁文件不能是符号链接。")
    handle = path.open("a+b")
    acquired = False
    try:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise ConfigurationError("该批次正由另一进程使用；请等待其退出后再续跑。") from None
        yield
    finally:
        if acquired:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
