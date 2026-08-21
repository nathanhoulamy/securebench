"""Portable comparisons for paths that may cross host/container filesystems."""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath


def portable_path_text(value: str) -> str:
    """Return a conservative comparison key for path text or a path pattern."""
    return unicodedata.normalize("NFC", value).casefold()


def portable_path_parts(path: str | PurePosixPath) -> tuple[str, ...]:
    """Return a conservative comparison key for a POSIX path.

    SecureBench workspaces may be host-backed by case-insensitive, Unicode-
    normalizing filesystems even though the Evaluation container is Linux.
    Security decisions therefore treat case and normalization aliases as the
    same path. This can reject a pair that would be distinct on some Linux
    hosts, but it cannot silently weaken a visibility or mount boundary.
    """
    return tuple(portable_path_text(part) for part in PurePosixPath(path).parts)


def portable_path_is_relative_to(
    path: str | PurePosixPath,
    parent: str | PurePosixPath,
) -> bool:
    """Return whether ``path`` is equal to or below ``parent`` portably."""
    path_parts = portable_path_parts(path)
    parent_parts = portable_path_parts(parent)
    return (
        len(path_parts) >= len(parent_parts)
        and path_parts[: len(parent_parts)] == parent_parts
    )


def portable_paths_equal(
    left: str | PurePosixPath,
    right: str | PurePosixPath,
) -> bool:
    """Return whether two POSIX paths may alias on a supported host."""
    return portable_path_parts(left) == portable_path_parts(right)


def portable_paths_overlap(
    left: str | PurePosixPath,
    right: str | PurePosixPath,
) -> bool:
    """Return whether either path is equal to or contains the other."""
    return portable_path_is_relative_to(left, right) or portable_path_is_relative_to(
        right, left
    )
