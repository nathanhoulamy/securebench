"""Small cross-platform advisory file-lock primitive."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None  # type: ignore[assignment]


class FileLockError(OSError):
    """An advisory file lock could not be acquired or released."""


@contextmanager
def exclusive_file_lock(path: str | Path, *, blocking: bool = True) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` for the duration of the context."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_descriptor(descriptor, blocking=blocking)
    except OSError as exc:
        os.close(descriptor)
        raise FileLockError(f"could not acquire lock: {lock_path}") from exc
    try:
        yield
    finally:
        try:
            _unlock_descriptor(descriptor)
        except OSError as exc:
            raise FileLockError(f"could not release lock: {lock_path}") from exc
        finally:
            os.close(descriptor)


def _lock_descriptor(descriptor: int, *, blocking: bool) -> None:
    if fcntl is not None:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(descriptor, flags)
        return
    if msvcrt is None:  # pragma: no cover - supported Python platforms provide one
        raise FileLockError("this platform does not provide file locking")
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
    os.lseek(descriptor, 0, os.SEEK_SET)
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    msvcrt.locking(descriptor, mode, 1)


def _unlock_descriptor(descriptor: int) -> None:
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    if msvcrt is None:  # pragma: no cover - supported Python platforms provide one
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
