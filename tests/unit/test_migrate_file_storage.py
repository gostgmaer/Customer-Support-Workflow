"""scripts/storage/migrate_file_storage.py - moves KnowledgeDocument
original files from whichever provider each one was uploaded to onto the
currently-configured target provider (spec: multi-provider KB upload
storage migration path). The target provider is exercised for real via
LocalDiskStorage; the "old" provider is a fake in-memory stand-in (no
real S3/Azure account needed - app.storage.s3_compatible/azure_blob
already have their own dedicated tests against the real SDKs).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import KnowledgeDocument
from app.storage.base import FileNotFoundInStorage
from app.storage.local_disk import LocalDiskStorage
from scripts.storage.migrate_file_storage import migrate


class _FakeOldProviderStorage:
    """Stands in for a real S3/Azure client already covered by
    tests/unit/test_file_storage.py - this test is about the migration
    script's own logic (which documents move, DB updates, dry-run,
    delete-old), not re-proving those providers' HTTP calls."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self.deleted: list[str] = []

    async def download(self, key: str) -> bytes:
        if key not in self._files:
            raise FileNotFoundInStorage(key)
        return self._files[key]

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        raise AssertionError("the fake old provider should never be uploaded to")

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        del self._files[key]


async def _make_document(db_session, *, storage_provider: str, storage_key: str) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        title="Some Policy",
        source=f"upload:abc123:{storage_key.split('/')[-1]}",
        category="general",
        version="1.0",
        effective_date=datetime.now(UTC),
        language="en",
        raw_text="Some policy content.",
        tenant_id=DEFAULT_TENANT_ID,
        storage_provider=storage_provider,
        storage_key=storage_key,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


def _patched_get_file_storage(fake_old: _FakeOldProviderStorage, target: LocalDiskStorage):
    def _get(provider: str | None = None):
        if provider == "s3":
            return fake_old
        return target

    return _get


@pytest.mark.asyncio
async def test_migrate_moves_a_document_to_the_target_provider(db_session, tmp_path, monkeypatch):
    key = f"knowledge/{DEFAULT_TENANT_ID}/doc1/policy.txt"
    document = await _make_document(db_session, storage_provider="s3", storage_key=key)
    fake_old = _FakeOldProviderStorage({key: b"policy bytes"})
    target = LocalDiskStorage(str(tmp_path))

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "scripts.storage.migrate_file_storage.get_file_storage",
            side_effect=_patched_get_file_storage(fake_old, target),
        ):
            await migrate(dry_run=False, delete_old=False)
    finally:
        get_settings.cache_clear()

    await db_session.refresh(document)
    assert document.storage_provider == "local"
    assert await target.download(key) == b"policy bytes"
    assert fake_old.deleted == []  # delete_old=False - old copy left alone


@pytest.mark.asyncio
async def test_migrate_dry_run_changes_nothing(db_session, tmp_path, monkeypatch):
    key = f"knowledge/{DEFAULT_TENANT_ID}/doc2/policy.txt"
    document = await _make_document(db_session, storage_provider="s3", storage_key=key)
    fake_old = _FakeOldProviderStorage({key: b"policy bytes"})
    target = LocalDiskStorage(str(tmp_path))

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "scripts.storage.migrate_file_storage.get_file_storage",
            side_effect=_patched_get_file_storage(fake_old, target),
        ):
            await migrate(dry_run=True, delete_old=False)
    finally:
        get_settings.cache_clear()

    await db_session.refresh(document)
    assert document.storage_provider == "s3"  # unchanged
    with pytest.raises(FileNotFoundInStorage):
        await target.download(key)


@pytest.mark.asyncio
async def test_migrate_documents_already_on_target_are_skipped(db_session, tmp_path, monkeypatch):
    key = f"knowledge/{DEFAULT_TENANT_ID}/doc3/policy.txt"
    document = await _make_document(db_session, storage_provider="local", storage_key=key)
    fake_old = _FakeOldProviderStorage({})
    target = LocalDiskStorage(str(tmp_path))

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "scripts.storage.migrate_file_storage.get_file_storage",
            side_effect=_patched_get_file_storage(fake_old, target),
        ):
            await migrate(dry_run=False, delete_old=False)
    finally:
        get_settings.cache_clear()

    await db_session.refresh(document)
    assert document.storage_provider == "local"  # never touched


@pytest.mark.asyncio
async def test_migrate_delete_old_removes_the_source_copy(db_session, tmp_path, monkeypatch):
    key = f"knowledge/{DEFAULT_TENANT_ID}/doc4/policy.txt"
    await _make_document(db_session, storage_provider="s3", storage_key=key)
    fake_old = _FakeOldProviderStorage({key: b"policy bytes"})
    target = LocalDiskStorage(str(tmp_path))

    monkeypatch.setenv("FILE_STORAGE_PROVIDER", "local")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "scripts.storage.migrate_file_storage.get_file_storage",
            side_effect=_patched_get_file_storage(fake_old, target),
        ):
            await migrate(dry_run=False, delete_old=True)
    finally:
        get_settings.cache_clear()

    assert fake_old.deleted == [key]
