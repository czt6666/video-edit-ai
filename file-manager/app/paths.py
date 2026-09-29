"""Path containment: the security core of the file manager.

Every client-supplied path flows through `safe_join`, which guarantees the
result stays inside the workspace root — rejecting `..` traversal, absolute
escapes, and symlinks that point outside the root. This module is pure (no
web/IO beyond realpath) so it can be exhaustively unit-tested.
"""
from __future__ import annotations

import os


class PathError(ValueError):
    """Raised when a client path is unsafe or malformed."""


def safe_join(root: str, rel: str) -> str:
    """Resolve `rel` (client-supplied) against `root`, confined to `root`.

    Returns an absolute, symlink-resolved path guaranteed to be `root` itself
    or a descendant of it. Raises PathError otherwise. The target need not
    exist (so it also works for upload/mkdir destinations).
    """
    root_abs = os.path.realpath(root)
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")

    parts: list[str] = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathError("path traversal ('..') is not allowed")
        if "\x00" in part:
            raise PathError("null byte in path")
        parts.append(part)

    candidate = os.path.join(root_abs, *parts)

    # Resolve symlinks on the parts that exist, then verify containment.
    real = os.path.realpath(candidate)
    if real != root_abs and not real.startswith(root_abs + os.sep):
        raise PathError("path escapes the workspace root")
    return real


def to_rel(root: str, abs_path: str) -> str:
    """Inverse of safe_join for display: workspace-relative POSIX path."""
    root_abs = os.path.realpath(root)
    rel = os.path.relpath(abs_path, root_abs)
    return "" if rel == "." else rel.replace(os.sep, "/")


def safe_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe basename (no directory parts)."""
    name = (name or "").replace("\\", "/")
    base = os.path.basename(name).strip()
    if base in ("", ".", "..") or "\x00" in base:
        raise PathError("invalid filename")
    return base
