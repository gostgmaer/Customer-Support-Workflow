"""Zero-setup file-storage provider (FILE_STORAGE_PROVIDER=local) - what
tests and an unconfigured dev checkout actually use, since none of the
cloud providers (R2/S3/Azure) have real zero-config credentials. Writes
under `Settings.local_storage_dir` (default ./data/uploads).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.storage.base import FileNotFoundInStorage


class LocalDiskStorage:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir).resolve()

    def _path_for(self, key: str) -> Path:
        # `key` is always our own uuid-based value (app.api.routes.knowledge),
        # never taken verbatim from a filename - resolved and bounds-checked
        # anyway as a defense-in-depth guard against path traversal.
        path = (self._base_dir / key).resolve()
        if path != self._base_dir and self._base_dir not in path.parents:
            raise ValueError(f"invalid storage key: {key}")
        return path

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path_for(key)
        await asyncio.to_thread(self._write, path, data)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def download(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise FileNotFoundInStorage(key) from exc

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)
