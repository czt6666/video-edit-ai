import pytest

from app.config import Config


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "raw" / "clip.mp4").write_bytes(b"\x00\x01\x02fakevideo")
    return tmp_path


@pytest.fixture()
def config(workspace):
    return Config(
        workspace_root=str(workspace),
        trust_proxy_auth=True,
        max_upload_bytes=0,
        default_upload_dir="raw",
    )


@pytest.fixture()
def client(config):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(config)
    with TestClient(app, headers={"X-Auth-User": "tester"}) as c:
        yield c
