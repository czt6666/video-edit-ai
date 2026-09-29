"""FastAPI transport layer for the auth service.

Responsibilities kept here (and nowhere else):
  - HTTP request/response shape and status codes
  - session cookie lifecycle
  - dependency wiring (config, per-request DB connection, current user)

All correctness/logic lives in `users.py` and `security.py`, which are pure
enough to unit-test without the web layer.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

from . import users as users_svc
from .config import Config
from .db import connect, init_db
from .security import create_token, decode_token


# --------------------------------------------------------------------------- #
# Request schemas (module scope so `from __future__ annotations` can resolve   #
# them — FastAPI resolves stringized annotations against module globals).      #
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


class CreateUserBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    is_admin: bool = False


# --------------------------------------------------------------------------- #
# App factory                                                                  #
# --------------------------------------------------------------------------- #
def create_app(config: Optional[Config] = None) -> FastAPI:
    cfg = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(cfg.db_path)
        try:
            init_db(conn)
            users_svc.seed_admin(conn, cfg.seed_admin_user, cfg.seed_admin_password)
        finally:
            conn.close()
        yield

    app = FastAPI(title="video-edit-ai auth", lifespan=lifespan)
    app.state.config = cfg

    # ----- dependencies ---------------------------------------------------- #
    def get_config() -> Config:
        return app.state.config

    def get_conn(cfg: Config = Depends(get_config)):
        conn = connect(cfg.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _decode_cookie(request: Request, cfg: Config) -> Optional[dict[str, Any]]:
        token = request.cookies.get(cfg.cookie_name)
        if not token:
            return None
        try:
            return decode_token(token, secret=cfg.jwt_secret)
        except jwt.PyJWTError:
            return None

    def current_user(
        request: Request,
        cfg: Config = Depends(get_config),
        conn=Depends(get_conn),
    ) -> dict[str, Any]:
        claims = _decode_cookie(request, cfg)
        if not claims:
            raise HTTPException(status_code=401, detail="not authenticated")
        user = users_svc.get_user_by_id(conn, int(claims["sub"]))
        if user is None:
            # Account deleted after the token was issued.
            raise HTTPException(status_code=401, detail="account no longer exists")
        return user

    def require_admin(user: dict = Depends(current_user)) -> dict[str, Any]:
        if not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="admin only")
        return user

    def _set_session_cookie(response: Response, token: str, max_age: Optional[int]):
        response.set_cookie(
            key=cfg.cookie_name,
            value=token,
            max_age=max_age,          # None -> session cookie (cleared on browser close)
            httponly=True,
            secure=cfg.cookie_secure,
            samesite=cfg.cookie_samesite,
            path="/",
        )

    # ----- static pages ---------------------------------------------------- #
    @app.get("/login")
    def login_page():
        return FileResponse(os.path.join(WEB_DIR, "login.html"))

    @app.get("/admin")
    def admin_page():
        # Auth is enforced client-side + by the API; the page itself is public
        # HTML that immediately calls /api/auth/me and redirects if needed.
        return FileResponse(os.path.join(WEB_DIR, "admin.html"))

    # ----- health ---------------------------------------------------------- #
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ----- auth ------------------------------------------------------------ #
    @app.post("/api/auth/login")
    def login(body: LoginBody, response: Response, conn=Depends(get_conn)):
        user = users_svc.authenticate(conn, body.username, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid username or password")
        ttl = cfg.remember_ttl if body.remember else cfg.token_ttl
        token = create_token(
            user_id=user["id"],
            username=user["username"],
            is_admin=user["is_admin"],
            secret=cfg.jwt_secret,
            ttl=ttl,
        )
        # remember -> persistent cookie; otherwise session cookie.
        _set_session_cookie(response, token, ttl if body.remember else None)
        return {"user": _public(user)}

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(cfg.cookie_name, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: dict = Depends(current_user)):
        return {"user": _public(user)}

    @app.get("/api/auth/verify")
    def verify(request: Request, cfg_: Config = Depends(get_config), conn=Depends(get_conn)):
        """Endpoint for Caddy `forward_auth`.

        200 + identity headers when the session is valid; 401 otherwise. Caddy
        copies the X-Auth-* headers upstream so the app/file-manager know who
        is calling without re-parsing the cookie.
        """
        claims = _decode_cookie(request, cfg_)
        if not claims:
            raise HTTPException(status_code=401, detail="not authenticated")
        user = users_svc.get_user_by_id(conn, int(claims["sub"]))
        if user is None:
            raise HTTPException(status_code=401, detail="account no longer exists")
        return JSONResponse(
            {"ok": True},
            headers={
                "X-Auth-User": user["username"],
                "X-Auth-User-Id": str(user["id"]),
                "X-Auth-Is-Admin": "1" if user["is_admin"] else "0",
            },
        )

    # ----- admin CRUD ------------------------------------------------------ #
    @app.get("/api/admin/users")
    def admin_list(_: dict = Depends(require_admin), conn=Depends(get_conn)):
        return {"users": users_svc.list_users(conn)}

    @app.post("/api/admin/users", status_code=201)
    def admin_create(
        body: CreateUserBody,
        _: dict = Depends(require_admin),
        conn=Depends(get_conn),
    ):
        try:
            created = users_svc.create_user(
                conn, body.username, body.password, is_admin=body.is_admin
            )
        except users_svc.DuplicateUser as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except users_svc.ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user": created}

    @app.delete("/api/admin/users/{user_id}")
    def admin_delete(
        user_id: int,
        admin: dict = Depends(require_admin),
        conn=Depends(get_conn),
    ):
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="cannot delete your own account")
        try:
            users_svc.delete_user(conn, user_id)
        except users_svc.UserNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except users_svc.ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    return app


def _public(user: dict[str, Any]) -> dict[str, Any]:
    """Strip anything sensitive before returning a user over the wire."""
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
    }


# Module-level app for `uvicorn app.main:app`.
app = create_app()
