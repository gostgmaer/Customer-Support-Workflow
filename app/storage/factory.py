"""Resolves `Settings.file_storage_provider` -> a concrete `FileStorage`,
mirroring `app.repositories.vector_store.get_vector_store`'s own
env-var-selected-backend factory pattern.
"""

from __future__ import annotations

from app.config import get_settings
from app.storage.azure_blob import AzureBlobStorage
from app.storage.base import FileStorage
from app.storage.local_disk import LocalDiskStorage
from app.storage.s3_compatible import S3CompatibleStorage


class StorageNotConfiguredError(Exception):
    """Raised when the selected provider is missing required credentials.
    Original-file storage is optional (spec: never block a KB upload on
    it) - app.api.routes.knowledge catches this specifically and skips
    storing the original file rather than failing the whole upload."""


def get_file_storage(provider: str | None = None) -> FileStorage:
    """`provider` overrides `Settings.file_storage_provider` - needed to
    read back a file stored under a *previously* selected provider after
    an operator has since switched (each KnowledgeDocument records the
    provider its own file actually lives on, see
    app.api.routes.knowledge's storage_provider/storage_key columns), and
    by scripts/storage/migrate_file_storage.py to hold both an old and a
    new provider's client at once during a migration."""
    settings = get_settings()
    provider = provider or settings.file_storage_provider

    if provider == "local":
        return LocalDiskStorage(settings.local_storage_dir)

    if provider == "r2":
        if not (
            settings.r2_account_id
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
            and settings.r2_bucket
        ):
            raise StorageNotConfiguredError(
                "FILE_STORAGE_PROVIDER=r2 requires R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, and R2_BUCKET"
            )
        return S3CompatibleStorage(
            bucket=settings.r2_bucket,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            # R2 has no region concept of its own; "auto" is Cloudflare's
            # documented placeholder for the S3-compatible API's required field.
            region="auto",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        )

    if provider == "s3":
        if not (settings.s3_access_key_id and settings.s3_secret_access_key and settings.s3_bucket):
            raise StorageNotConfiguredError(
                "FILE_STORAGE_PROVIDER=s3 requires S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, and S3_BUCKET"
            )
        return S3CompatibleStorage(
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )

    if provider == "azure":
        if not (settings.azure_storage_connection_string and settings.azure_storage_container):
            raise StorageNotConfiguredError(
                "FILE_STORAGE_PROVIDER=azure requires AZURE_STORAGE_CONNECTION_STRING and "
                "AZURE_STORAGE_CONTAINER"
            )
        return AzureBlobStorage(
            connection_string=settings.azure_storage_connection_string,
            container=settings.azure_storage_container,
        )

    raise ValueError(f"Unknown FILE_STORAGE_PROVIDER: {provider!r}")
