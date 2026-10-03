import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_ready_returns_503_when_database_unreachable(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise ConnectionRefusedError("db down")

    monkeypatch.setattr("app.main.engine", BrokenEngine())
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "down"
