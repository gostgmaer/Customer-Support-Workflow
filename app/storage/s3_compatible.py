"""S3-compatible file-storage provider - backs both FILE_STORAGE_PROVIDER
values "r2" (Cloudflare R2, the default) and "s3" (real AWS S3), since R2
implements the S3 API and only differs by needing a custom account-specific
`endpoint_url` (app.storage.factory builds that). One implementation for
both, verified against the real installed boto3 (1.43) before writing this -
not guessed from documentation.

boto3 itself is synchronous; every call is wrapped in `asyncio.to_thread`
rather than adding a less-mature async-S3 dependency (aioboto3), matching
how rarely this runs (once per KB upload/occasional download or delete),
not a hot path.
"""

from __future__ import annotations

import asyncio

import boto3
from botocore.exceptions import ClientError

from app.storage.base import FileNotFoundInStorage

_NOT_FOUND_CODES = {"NoSuchKey", "404"}


class S3CompatibleStorage:
    def __init__(
        self,
        *,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            endpoint_url=endpoint_url,
        )

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def download(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                raise FileNotFoundInStorage(key) from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
