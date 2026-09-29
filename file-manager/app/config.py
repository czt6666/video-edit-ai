"""File-manager configuration from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # Root of the shared file tree. In production this is the rclone/TOS mount.
    workspace_root: str = os.environ.get("FM_WORKSPACE_ROOT", "/workspace")
    # When true, require the gateway-injected X-Auth-User header (Caddy sets it
    # only after forward_auth succeeds). Disable only for isolated unit tests.
    trust_proxy_auth: bool = _bool("FM_TRUST_PROXY_AUTH", True)
    # Reject uploads larger than this (bytes). 0 = unlimited.
    max_upload_bytes: int = int(os.environ.get("FM_MAX_UPLOAD_BYTES", "0"))
    # Default directory new uploads land in when the client omits a target.
    default_upload_dir: str = os.environ.get("FM_DEFAULT_UPLOAD_DIR", "raw")

    @staticmethod
    def from_env() -> "Config":
        return Config(
            workspace_root=os.environ.get("FM_WORKSPACE_ROOT", "/workspace"),
            trust_proxy_auth=_bool("FM_TRUST_PROXY_AUTH", True),
            max_upload_bytes=int(os.environ.get("FM_MAX_UPLOAD_BYTES", "0")),
            default_upload_dir=os.environ.get("FM_DEFAULT_UPLOAD_DIR", "raw"),
        )
