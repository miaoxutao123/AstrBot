"""Gateway control-plane static UI delivery."""

from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus


def test_gateway_ui_and_assets_are_served() -> None:
    bus = MemoryEventBus()
    app = create_app(
        AdapterRuntime(AdapterRegistry(), bus),
        bus,
        [ApiKey("admin", "secret", frozenset({"*"}))],
    )
    with TestClient(app) as client:
        index = client.get("/ui")
        spa_fallback = client.get("/ui/connections")
        asset = client.get("/ui/assets/app.js")

    assert index.status_code == 200
    assert "AstrBot Gateway" in index.text
    assert spa_fallback.status_code == 200
    assert asset.status_code == 200
    assert "adapter-instances" in asset.text
