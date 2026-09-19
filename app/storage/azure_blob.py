"""Azure Blob Storage file-storage provider (FILE_STORAGE_PROVIDER=azure).
Uses the SDK's genuine async client (azure.storage.blob.aio), verified
against the real installed azure-storage-blob package before writing this.

A fresh `BlobServiceClient` is opened and closed per call rather than kept
alive across the app's lifetime - this runs rarely (once per KB upload/
occasional download or delete), and avoids wiring a long-lived client
into app.main's lifespan for a rarely-used, optional integration (the
same "cheap to reconnect, not a hot path" tradeoff app.integrations.base's
per-call httpx clients already make elsewhere in this codebase).
"""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from app.storage.base import FileNotFoundInStorage


class AzureBlobStorage:
    def __init__(self, *, connection_string: str, container: str) -> None:
        self._connection_string = connection_string
        self._container = container

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        async with BlobServiceClient.from_connection_string(self._connection_string) as service:
            blob = service.get_blob_client(container=self._container, blob=key)
            settings = ContentSettings(content_type=content_type)
            await blob.upload_blob(data, overwrite=True, content_settings=settings)

    async def download(self, key: str) -> bytes:
        async with BlobServiceClient.from_connection_string(self._connection_string) as service:
            blob = service.get_blob_client(container=self._container, blob=key)
            try:
                downloader = await blob.download_blob()
            except ResourceNotFoundError as exc:
                raise FileNotFoundInStorage(key) from exc
            return await downloader.readall()

    async def delete(self, key: str) -> None:
        async with BlobServiceClient.from_connection_string(self._connection_string) as service:
            blob = service.get_blob_client(container=self._container, blob=key)
            try:
                await blob.delete_blob()
            except ResourceNotFoundError as exc:
                raise FileNotFoundInStorage(key) from exc
