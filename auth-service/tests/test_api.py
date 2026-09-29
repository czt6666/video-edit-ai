"""End-to-end HTTP tests through the FastAPI TestClient."""


def _login(client, username, password, remember=False):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "remember": remember},
    )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_static_pages_served(client):
    for path in ("/login", "/admin"):
        r = client.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<!DOCTYPE html>" in r.text


def test_seed_admin_can_login(client):
    r = _login(client, "admin", "admin-pass")
    assert r.status_code == 200
    assert r.json()["user"] == {"id": 1, "username": "admin", "is_admin": True}
    # Session cookie set.
    assert "veai_session" in r.cookies


def test_login_bad_credentials(client):
    assert _login(client, "admin", "nope").status_code == 401
    assert _login(client, "ghost", "whatever").status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    _login(client, "admin", "admin-pass")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin"


def test_verify_endpoint_sets_identity_headers(client):
    assert client.get("/api/auth/verify").status_code == 401
    _login(client, "admin", "admin-pass")
    r = client.get("/api/auth/verify")
    assert r.status_code == 200
    assert r.headers["X-Auth-User"] == "admin"
    assert r.headers["X-Auth-Is-Admin"] == "1"


def test_logout_clears_session(client):
    _login(client, "admin", "admin-pass")
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_admin_crud_flow(client):
    _login(client, "admin", "admin-pass")

    # create
    r = client.post(
        "/api/admin/users",
        json={"username": "editor1", "password": "password1", "is_admin": False},
    )
    assert r.status_code == 201
    new_id = r.json()["user"]["id"]

    # duplicate -> 409
    dup = client.post(
        "/api/admin/users",
        json={"username": "editor1", "password": "password1"},
    )
    assert dup.status_code == 409

    # invalid -> 400
    bad = client.post(
        "/api/admin/users",
        json={"username": "bad name", "password": "password1"},
    )
    assert bad.status_code == 400

    # list contains both
    listing = client.get("/api/admin/users").json()["users"]
    assert {x["username"] for x in listing} == {"admin", "editor1"}

    # the new user can log in
    fresh = client.__class__(client.app)  # separate cookie jar
    assert _login(fresh, "editor1", "password1").status_code == 200

    # delete
    assert client.delete(f"/api/admin/users/{new_id}").status_code == 200
    listing = client.get("/api/admin/users").json()["users"]
    assert {x["username"] for x in listing} == {"admin"}


def test_non_admin_cannot_reach_admin_endpoints(client):
    _login(client, "admin", "admin-pass")
    client.post(
        "/api/admin/users",
        json={"username": "plain", "password": "password1", "is_admin": False},
    )
    client.post("/api/auth/logout")
    client.cookies.clear()

    _login(client, "plain", "password1")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post(
        "/api/admin/users", json={"username": "x", "password": "password1"}
    ).status_code == 403


def test_admin_cannot_delete_self(client):
    _login(client, "admin", "admin-pass")
    assert client.delete("/api/admin/users/1").status_code == 400
