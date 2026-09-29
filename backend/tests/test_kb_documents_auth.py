import uuid

import pytest


@pytest.mark.asyncio
async def test_kb_list_requires_auth(client):
    response = await client.get("/api/v1/knowledge-bases/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_kb_create_requires_auth(client):
    response = await client.post(
        "/api/v1/knowledge-bases/", json={"name": "Test KB"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_document_list_requires_auth(client):
    kb_id = uuid.uuid4()
    response = await client.get(f"/api/v1/knowledge-bases/{kb_id}/documents/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_document_upload_requires_auth(client):
    kb_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        files={"file": ("test.pdf", b"content", "application/pdf")},
    )
    assert response.status_code == 401
