import io


def test_health(client, config):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["root"] == config.workspace_root


def test_auth_required_when_proxy_trusted(config):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(config)) as c:  # no X-Auth-User header
        assert c.get("/api/files/list").status_code == 401


def test_list_root_dirs_first(client):
    r = client.get("/api/files/list")
    assert r.status_code == 200
    entries = r.json()["entries"]
    names = [e["name"] for e in entries]
    # dirs (outputs, raw) come before any file, alphabetical within group
    assert names[:2] == ["outputs", "raw"]
    raw = next(e for e in entries if e["name"] == "raw")
    assert raw["type"] == "dir"


def test_list_subdir_and_stat(client):
    r = client.get("/api/files/list", params={"path": "raw"})
    assert [e["name"] for e in r.json()["entries"]] == ["clip.mp4"]
    st = client.get("/api/files/stat", params={"path": "raw/clip.mp4"}).json()
    assert st["type"] == "file" and st["size"] > 0


def test_list_traversal_rejected(client):
    assert client.get("/api/files/list", params={"path": "../.."}).status_code == 400


def test_list_missing_404(client):
    assert client.get("/api/files/list", params={"path": "nope"}).status_code == 404


def test_upload_default_dir(client):
    files = {"file": ("new.mp4", io.BytesIO(b"hello-bytes"), "video/mp4")}
    r = client.post("/api/files/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "raw/new.mp4"
    assert body["size"] == len(b"hello-bytes")
    # now visible in listing
    names = [e["name"] for e in client.get("/api/files/list", params={"path": "raw"}).json()["entries"]]
    assert "new.mp4" in names


def test_upload_to_subdir_and_sanitizes_name(client):
    files = {"file": ("../../evil.txt", io.BytesIO(b"data"), "text/plain")}
    r = client.post("/api/files/upload", params={"path": "outputs"}, files=files)
    assert r.status_code == 200
    assert r.json()["path"] == "outputs/evil.txt"  # stripped to basename


def test_upload_size_limit():
    from fastapi.testclient import TestClient

    from app.config import Config
    from app.main import create_app

    import tempfile, os
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    cfg = Config(workspace_root=d, trust_proxy_auth=True, max_upload_bytes=4, default_upload_dir="raw")
    with TestClient(create_app(cfg), headers={"X-Auth-User": "t"}) as c:
        files = {"file": ("big.bin", io.BytesIO(b"toolong"), "application/octet-stream")}
        assert c.post("/api/files/upload", files=files).status_code == 413
        # partial file cleaned up
        assert not os.path.exists(os.path.join(d, "raw", "big.bin"))
        assert not os.path.exists(os.path.join(d, "raw", "big.bin.part"))


def test_download(client):
    r = client.get("/api/files/download", params={"path": "raw/clip.mp4"})
    assert r.status_code == 200
    assert r.content == b"\x00\x01\x02fakevideo"


def test_download_missing(client):
    assert client.get("/api/files/download", params={"path": "raw/ghost.mp4"}).status_code == 404


def test_mkdir_and_delete_flow(client):
    assert client.post("/api/files/mkdir", params={"path": "projects/ep1"}).status_code == 200
    assert client.get("/api/files/list", params={"path": "projects"}).json()["entries"][0]["name"] == "ep1"
    # delete non-empty dir without recursive -> 409
    files = {"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}
    client.post("/api/files/upload", params={"path": "projects/ep1"}, files=files)
    assert client.request("DELETE", "/api/files", params={"path": "projects/ep1"}).status_code == 409
    # recursive works
    assert client.request(
        "DELETE", "/api/files", params={"path": "projects/ep1", "recursive": True}
    ).status_code == 200
    assert client.get("/api/files/list", params={"path": "projects"}).json()["entries"] == []


def test_delete_file(client):
    assert client.request("DELETE", "/api/files", params={"path": "raw/clip.mp4"}).status_code == 200
    assert client.get("/api/files/stat", params={"path": "raw/clip.mp4"}).status_code == 404


def test_cannot_delete_root(client):
    assert client.request("DELETE", "/api/files", params={"path": ""}).status_code == 400
