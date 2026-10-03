"""The only KnowledgeConnector in V1: reads a FastAPI UploadFile the browser
already sent via multipart form data. Wraps `upload_safety.read_limited`
unchanged, so behavior is identical to pre-abstraction V1.
"""

from __future__ import annotations

from fastapi import UploadFile

from app.domains.documents.connectors.base import KnowledgeConnector, RawFile
from app.domains.documents.upload_safety import read_limited


class UploadConnector(KnowledgeConnector):
    async def fetch(
        self,
        source: UploadFile,
        *,
        max_bytes: int,
        max_mb: int | None = None,
    ) -> RawFile:
        content = await read_limited(source, max_bytes, max_mb)
        return RawFile(
            filename=source.filename or "file",
            content=content,
            content_type=source.content_type or "application/octet-stream",
        )
