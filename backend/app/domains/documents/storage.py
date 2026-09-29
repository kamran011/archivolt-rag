"""
Supabase Storage integration via direct REST API calls (httpx), using the
service_role key. This bypasses Storage RLS — authorization is enforced at
the application layer (organization_id / knowledge_base_id path scoping).
"""

import uuid

import httpx
import structlog

from app.config import settings
from app.core.exceptions import StorageError

logger = structlog.get_logger()


class StorageService:
    def __init__(self) -> None:
        self.base_url = f"{settings.SUPABASE_URL}/storage/v1"
        self.bucket = settings.STORAGE_BUCKET
        self.headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        }

    def build_path(
        self,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
        doc_id: uuid.UUID,
        file_name: str,
    ) -> str:
        return f"{org_id}/{kb_id}/{doc_id}/{file_name}"

    async def upload_file(
        self,
        storage_path: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        url = f"{self.base_url}/object/{self.bucket}/{storage_path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={**self.headers, "Content-Type": content_type},
                content=content,
            )
        if response.status_code not in (200, 201):
            logger.error(
                "storage_upload_failed",
                status=response.status_code,
                body=response.text[:500],
            )
            raise StorageError(f"Failed to upload file: {response.status_code}")
        return storage_path

    async def download_file(self, storage_path: str) -> bytes:
        url = f"{self.base_url}/object/{self.bucket}/{storage_path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=self.headers)
        if response.status_code != 200:
            raise StorageError(f"Failed to download file: {response.status_code}")
        return response.content

    async def delete_file(self, storage_path: str) -> None:
        url = f"{self.base_url}/object/{self.bucket}/{storage_path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(url, headers=self.headers)
        if response.status_code not in (200, 204):
            logger.warning(
                "storage_delete_failed",
                status=response.status_code,
                path=storage_path,
            )

    async def get_signed_url(self, storage_path: str, expires_in: int = 3600) -> str:
        url = f"{self.base_url}/object/sign/{self.bucket}/{storage_path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={**self.headers, "Content-Type": "application/json"},
                json={"expiresIn": expires_in},
            )
        if response.status_code != 200:
            raise StorageError(f"Failed to create signed URL: {response.status_code}")
        signed_path = response.json()["signedURL"]
        return f"{settings.SUPABASE_URL}/storage/v1{signed_path}"


storage_service = StorageService()
