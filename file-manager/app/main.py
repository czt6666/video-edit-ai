"""File-manager HTTP service over the shared workspace (TOS mount).

Endpoints (all under /api/files) let the browser list, upload, download,
preview, delete and mkdir inside the workspace root. Authentication is
delegated to the gateway: Caddy runs forward_auth against the auth-service and
injects `X-Auth-User`; this service simply requires that header to be present
when `trust_proxy_auth` is on. Path safety is enforced by `safe_join`.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .config import Config
from .paths import PathError, safe_filename, safe_join, to_rel

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


def create_app(config: Optional[Config] = None) -> FastAPI:
    cfg = config or Config.from_env()
    app = FastAPI(title="video-edit-ai file-manager")
    app.state.config = cfg

    def get_config() -> Config:
        return app.state.config

    def require_user(
        cfg: Config = Depends(get_config),
        x_auth_user: Optional[str] = Header(default=None),
    ) -> str:
        if cfg.trust_proxy_auth and not x_auth_user:
            raise HTTPException(status_code=401, detail="not authenticated")
        return x_auth_user or "anonymous"

    def resolve(rel: str) -> str:
        try:
            return safe_join(cfg.workspace_root, rel)
        except PathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _entry(abs_path: str) -> dict[str, Any]:
        st = os.stat(abs_path)
        is_dir = os.path.isdir(abs_path)
        return {
            "name": os.path.basename(abs_path),
            "path": to_rel(cfg.workspace_root, abs_path),
            "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else st.st_size,
            "mtime": int(st.st_mtime),
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "root": cfg.workspace_root}

    @app.get("/files")
    def files_page():
        # Finder-like file manager UI. Auth is enforced by the gateway; the page
        # also calls /api/auth/me and redirects to /login if unauthenticated.
        return FileResponse(os.path.join(_WEB_DIR, "index.html"))

    @app.get("/api/files/list")
    def list_dir(
        path: str = Query(default=""),
        _user: str = Depends(require_user),
    ):
        target = resolve(path)
        if not os.path.exists(target):
            raise HTTPException(status_code=404, detail="path not found")
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="not a directory")
        entries = []
        for name in os.listdir(target):
            if name == ".DS_Store":
                continue
            try:
                entries.append(_entry(os.path.join(target, name)))
            except FileNotFoundError:
                continue  # raced deletion
        # Directories first, then files; each group alphabetical.
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return {"path": to_rel(cfg.workspace_root, target), "entries": entries}

    @app.get("/api/files/stat")
    def stat_path(path: str = Query(...), _user: str = Depends(require_user)):
        target = resolve(path)
        if not os.path.exists(target):
            raise HTTPException(status_code=404, detail="path not found")
        return _entry(target)

    @app.post("/api/files/mkdir")
    def mkdir(path: str = Query(...), _user: str = Depends(require_user)):
        target = resolve(path)
        if target == os.path.realpath(cfg.workspace_root):
            raise HTTPException(status_code=400, detail="cannot recreate root")
        os.makedirs(target, exist_ok=True)
        return {"ok": True, "path": to_rel(cfg.workspace_root, target)}

    @app.post("/api/files/upload")
    async def upload(
        path: str = Query(default=""),
        file: UploadFile = File(...),
        _user: str = Depends(require_user),
    ):
        # `path` is the destination directory (relative). Default: raw/.
        dest_dir_rel = path or cfg.default_upload_dir
        dest_dir = resolve(dest_dir_rel)
        os.makedirs(dest_dir, exist_ok=True)
        try:
            fname = safe_filename(file.filename or "")
        except PathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dest = safe_join(cfg.workspace_root, os.path.join(to_rel(cfg.workspace_root, dest_dir), fname))

        written = 0
        tmp = dest + ".part"
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = await file.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if cfg.max_upload_bytes and written > cfg.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="file too large")
                    out.write(chunk)
            os.replace(tmp, dest)
        except HTTPException:
            _silent_remove(tmp)
            raise
        except OSError as exc:
            _silent_remove(tmp)
            raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
        finally:
            await file.close()
        return {"ok": True, "path": to_rel(cfg.workspace_root, dest), "size": written}

    @app.get("/api/files/download")
    def download(path: str = Query(...), _user: str = Depends(require_user)):
        target = resolve(path)
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="file not found")
        # FileResponse honours Range requests -> in-browser video seeking.
        return FileResponse(target, filename=os.path.basename(target))

    @app.delete("/api/files")
    def delete(
        path: str = Query(...),
        recursive: bool = Query(default=False),
        _user: str = Depends(require_user),
    ):
        target = resolve(path)
        if target == os.path.realpath(cfg.workspace_root):
            raise HTTPException(status_code=400, detail="cannot delete the workspace root")
        if not os.path.exists(target):
            raise HTTPException(status_code=404, detail="path not found")
        if os.path.isdir(target):
            if recursive:
                shutil.rmtree(target)
            else:
                try:
                    os.rmdir(target)
                except OSError as exc:
                    raise HTTPException(
                        status_code=409, detail="directory not empty (use recursive=true)"
                    ) from exc
        else:
            os.remove(target)
        return {"ok": True}

    return app


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


app = create_app()
