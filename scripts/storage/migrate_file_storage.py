"""Moves KnowledgeDocument original files from whichever provider each one
was uploaded to, onto the CURRENTLY configured provider
(Settings.file_storage_provider) - for when an operator switches
FILE_STORAGE_PROVIDER (e.g. r2 -> s3 -> azure) and wants existing uploads
to actually live on the new provider too, not just new ones going
forward.

Every document's file keeps the same storage_key across providers (it was
already unique - "knowledge/<tenant>/<document_id>/<filename>") - only
`storage_provider` changes once the copy succeeds. The old provider's
copy is left in place unless --delete-old is passed, so a failed or
partial migration never loses data.

Usage:
    python scripts/storage/migrate_file_storage.py [--dry-run] [--delete-old]

Set FILE_STORAGE_PROVIDER (and that provider's credentials) to the
*target* provider before running - this migrates TO whatever is
currently configured, matching how every other part of this app treats
Settings.file_storage_provider as "the active choice."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_sessionmaker, init_models  # noqa: E402
from app.domain.models import KnowledgeDocument  # noqa: E402
from app.storage.base import FileNotFoundInStorage  # noqa: E402
from app.storage.factory import StorageNotConfiguredError, get_file_storage  # noqa: E402


async def migrate(*, dry_run: bool, delete_old: bool) -> None:
    await init_models()

    target_provider = get_settings().file_storage_provider
    try:
        target_storage = get_file_storage(target_provider)
    except StorageNotConfiguredError as exc:
        print(f"Target provider {target_provider!r} is not configured: {exc}")
        return

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.storage_key.is_not(None))
        )
        documents = list(result.scalars().all())

        to_migrate = [d for d in documents if d.storage_provider != target_provider]
        already_there = len(documents) - len(to_migrate)
        print(
            f"{len(documents)} document(s) have a stored file; {already_there} already on "
            f"{target_provider!r}; {len(to_migrate)} to migrate."
        )

        migrated, failed = 0, 0
        for document in to_migrate:
            source_provider = document.storage_provider
            storage_key = document.storage_key
            assert storage_key is not None  # guaranteed by the WHERE clause above
            print(f"  {document.id} ({document.title!r}): {source_provider} -> {target_provider}", end="")
            if dry_run:
                print("  [dry-run]")
                continue

            try:
                source_storage = get_file_storage(source_provider)
                data = await source_storage.download(storage_key)
                content_type = "application/octet-stream"
                await target_storage.upload(storage_key, data, content_type=content_type)
            except (StorageNotConfiguredError, FileNotFoundInStorage, Exception) as exc:  # noqa: BLE001
                print(f"  FAILED: {exc}")
                failed += 1
                continue

            document.storage_provider = target_provider
            await session.commit()
            migrated += 1
            print("  done")

            if delete_old:
                try:
                    old_storage = get_file_storage(source_provider)
                    await old_storage.delete(storage_key)
                except Exception as exc:  # noqa: BLE001 - best-effort cleanup, migration already succeeded
                    print(f"    (could not delete old copy on {source_provider}: {exc})")

        print(f"\nDone: {migrated} migrated, {failed} failed" + (" (dry run)" if dry_run else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying anything")
    parser.add_argument(
        "--delete-old",
        action="store_true",
        help="Delete each file from its old provider once the new copy succeeds",
    )
    args = parser.parse_args()

    asyncio.run(migrate(dry_run=args.dry_run, delete_old=args.delete_old))


if __name__ == "__main__":
    main()
