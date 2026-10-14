from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.csit_integration_v1.config import Settings
from src.km_dev_upload.api import create_app

def test_public_bridge_cannot_open_search(tmp_path):
    def deny(_):
        raise HTTPException(401, "login required")
    app=create_app(Settings(storage_root=str(tmp_path)),object(),object(),deny,set(),"da40")
    client=TestClient(app)
    script=client.get("/dev-chat-bridge.js")
    assert script.status_code==200 and "window.sendMessage" in script.text
    assert script.headers["Cache-Control"]=="no-store"
    assert client.get("/api/dev-upload/search?term=DA40_ONLY_test").status_code==401
