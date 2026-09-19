"""app.storage.* - the pluggable original-file-storage backend (spec:
multi-provider KB upload storage, R2 default). LocalDiskStorage is tested
for real (actual file I/O); S3CompatibleStorage (backs both "r2" and
"s3") is tested against botocore's own Stubber, the SDK's official
testing tool - no real AWS/R2 account needed. AzureBlobStorage's async
client isn't Stubber-compatible, so it's tested via unittest.mock against
the exact methods app.storage.azure_blob calls.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError
from botocore.stub import Stubber

from app.storage.azure_blob import AzureBlobStorage
from app.storage.base import FileNotFoundInStorage
from app.storage.factory import StorageNotConfiguredError, get_file_storage
from app.storage.local_disk import LocalDiskStorage
from app.storage.s3_compatible import S3CompatibleStorage


@pytest.mark.asyncio
async def test_local_disk_round_trips_a_real_file(tmp_path: Path):
    storage = LocalDiskStorage(str(tmp_path))

    await storage.upload("docs/policy.pdf", b"pdf bytes", content_type="application/pdf")
    data = await storage.download("docs/policy.pdf")

    assert data == b"pdf bytes"
    assert (tmp_path / "docs" / "policy.pdf").exists()


@pytest.mark.asyncio
async def test_local_disk_download_of_missing_key_raises(tmp_path: Path):
    storage = LocalDiskStorage(str(tmp_path))
    with pytest.raises(FileNotFoundInStorage):
        await storage.download("nope.txt")


@pytest.mark.asyncio
async def test_local_disk_delete_is_idempotent(tmp_path: Path):
    storage = LocalDiskStorage(str(tmp_path))
    await storage.upload("a.txt", b"x", content_type="text/plain")
    await storage.delete("a.txt")
    await storage.delete("a.txt")  # deleting again must not raise
    with pytest.raises(FileNotFoundInStorage):
        await storage.download("a.txt")


@pytest.mark.asyncio
async def test_local_disk_rejects_path_traversal():
    storage = LocalDiskStorage("/tmp/kb-uploads")
    with pytest.raises(ValueError, match="invalid storage key"):
        await storage.download("../../etc/passwd")


@pytest.mark.asyncio
async def test_s3_compatible_upload_and_download_round_trip():
    storage = S3CompatibleStorage(
        bucket="test-bucket", access_key_id="x", secret_access_key="y", region="auto"
    )
    stubber = Stubber(storage._client)  # noqa: SLF001 - the SDK's own recommended test seam
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "test-bucket", "Key": "k1", "Body": b"hello", "ContentType": "text/plain"},
    )
    stubber.add_response(
        "get_object", {"Body": io.BytesIO(b"hello")}, {"Bucket": "test-bucket", "Key": "k1"}
    )
    with stubber:
        await storage.upload("k1", b"hello", content_type="text/plain")
        data = await storage.download("k1")

    assert data == b"hello"


@pytest.mark.asyncio
async def test_s3_compatible_missing_key_raises_file_not_found():
    storage = S3CompatibleStorage(bucket="b", access_key_id="x", secret_access_key="y", region="auto")
    stubber = Stubber(storage._client)  # noqa: SLF001
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with stubber, pytest.raises(FileNotFoundInStorage):
        await storage.download("missing")


@pytest.mark.asyncio
async def test_s3_compatible_other_error_is_not_swallowed():
    storage = S3CompatibleStorage(bucket="b", access_key_id="x", secret_access_key="y", region="auto")
    stubber = Stubber(storage._client)  # noqa: SLF001
    stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with stubber, pytest.raises(Exception, match="AccessDenied"):
        await storage.download("k1")


def test_r2_and_s3_share_one_implementation():
    """R2 is S3-API-compatible - app.storage.factory only varies the
    endpoint_url, never the client class."""
    r2_style = S3CompatibleStorage(
        bucket="b", access_key_id="x", secret_access_key="y", region="auto",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
    )
    s3_style = S3CompatibleStorage(bucket="b", access_key_id="x", secret_access_key="y", region="us-east-1")
    assert type(r2_style) is type(s3_style)


@pytest.mark.asyncio
async def test_azure_blob_upload_and_download_round_trip():
    storage = AzureBlobStorage(connection_string="UseDevelopmentStorage=true", container="kb")

    mock_downloader = AsyncMock()
    mock_downloader.readall = AsyncMock(return_value=b"hello")
    mock_blob_client = AsyncMock()
    mock_blob_client.download_blob = AsyncMock(return_value=mock_downloader)
    mock_service = AsyncMock()
    mock_service.get_blob_client = lambda container, blob: mock_blob_client
    mock_service.__aenter__ = AsyncMock(return_value=mock_service)
    mock_service.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.storage.azure_blob.BlobServiceClient.from_connection_string", return_value=mock_service
    ):
        await storage.upload("k1", b"hello", content_type="text/plain")
        data = await storage.download("k1")

    assert data == b"hello"
    mock_blob_client.upload_blob.assert_awaited_once()


@pytest.mark.asyncio
async def test_azure_blob_missing_key_raises_file_not_found():
    storage = AzureBlobStorage(connection_string="UseDevelopmentStorage=true", container="kb")

    mock_blob_client = AsyncMock()
    mock_blob_client.download_blob = AsyncMock(side_effect=ResourceNotFoundError("not found"))
    mock_service = AsyncMock()
    mock_service.get_blob_client = lambda container, blob: mock_blob_client
    mock_service.__aenter__ = AsyncMock(return_value=mock_service)
    mock_service.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.storage.azure_blob.BlobServiceClient.from_connection_string", return_value=mock_service
    ), pytest.raises(FileNotFoundInStorage):
        await storage.download("missing")


def test_get_file_storage_defaults_to_r2(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("FILE_STORAGE_PROVIDER", raising=False)
    assert get_settings().file_storage_provider == "r2"
    get_settings.cache_clear()


def test_get_file_storage_r2_requires_credentials(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "r2")
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(StorageNotConfiguredError):
            get_file_storage()
    finally:
        get_settings.cache_clear()


def test_get_file_storage_local_needs_no_credentials(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    get_settings.cache_clear()
    try:
        storage = get_file_storage()
        assert isinstance(storage, LocalDiskStorage)
    finally:
        get_settings.cache_clear()
