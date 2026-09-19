"""File-storage abstraction (spec: KB upload keeps the original file, not
just its extracted text) - one provider active at a time
(`app.config.Settings.file_storage_provider`), the same pluggable-backend
pattern this app already uses for `VECTOR_BACKEND`/`CHECKPOINT_BACKEND`.
Every provider stores bytes under an opaque `key` and never returns a
provider-specific URL - callers (app.api.routes.knowledge) go through this
same interface to read a file back regardless of which provider wrote it,
which is what makes switching providers later safe (the stored `key` and
`storage_provider` are recorded per-document; see
scripts/storage/migrate_file_storage.py for moving existing files to a
newly-selected provider).
"""

from __future__ import annotations

from typing import Protocol


class FileNotFoundInStorage(Exception):
    """Raised when a requested key doesn't exist in the configured
    provider - callers turn this into a 404, never a 500."""

    def __init__(self, key: str) -> None:
        super().__init__(f"No object found for key: {key}")
        self.key = key


class FileStorage(Protocol):
    async def upload(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def download(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
