"""Document loaders (spec §8: Documents -> Loader -> Cleaning)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class LoadedDocument:
    title: str
    source: str
    category: str
    version: str
    effective_date: datetime
    expiration_date: datetime | None
    language: str
    text: str


def clean_text(text: str) -> str:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_markdown_with_frontmatter(path: Path) -> LoadedDocument:
    """Loads a markdown file with YAML frontmatter, e.g.:

        ---
        title: Refund Policy
        category: refunds
        version: "1.2"
        effective_date: 2026-01-01
        expiration_date:
        ---
        # body...
    """
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, frontmatter, body = raw.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}
    effective_date = _parse_date(meta.get("effective_date"))
    if effective_date is None:
        raise ValueError(f"{path} frontmatter is missing required 'effective_date'")
    return LoadedDocument(
        title=meta.get("title", path.stem),
        source=str(path),
        category=meta.get("category", "general"),
        version=str(meta.get("version", "1.0")),
        effective_date=effective_date,
        expiration_date=_parse_date(meta.get("expiration_date")),
        language=meta.get("language", "en"),
        text=clean_text(body),
    )


def _parse_date(value) -> datetime | None:  # noqa: ANN001
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    from datetime import date

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def load_knowledge_directory(directory: Path) -> list[LoadedDocument]:
    return [load_markdown_with_frontmatter(p) for p in sorted(directory.glob("*.md"))]
