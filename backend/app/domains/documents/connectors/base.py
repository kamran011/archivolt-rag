"""KnowledgeConnector: the pluggable seam for "where does a document's bytes
come from".

V1 ships a single implementation (`UploadConnector`, wrapping the existing
bounded multipart read in `upload_safety.read_limited` unchanged). Later
versions add Website, S3, Google Drive, Dropbox and SharePoint connectors
behind the same interface - the ingestion pipeline (validate -> sniff ->
store -> parse -> chunk -> embed) depends only on `KnowledgeConnector`
producing a `RawFile`, never on how those bytes were acquired.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class RawFile:
    filename: str
    content: bytes
    content_type: str


class KnowledgeConnector(ABC):
    @abstractmethod
    async def fetch(
        self,
        source: Any,
        *,
        max_bytes: int,
        max_mb: int | None = None,
    ) -> RawFile:
        raise NotImplementedError
