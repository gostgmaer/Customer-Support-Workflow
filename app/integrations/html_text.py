"""Minimal HTML-to-plaintext stripping for Confluence's storage-format
body (spec: Phase 9.3). Confluence Cloud's page content comes back as
XHTML-ish markup (`body.storage.value`); Notion's API returns structured
JSON blocks instead (no HTML), so only the Confluence connector needs
this.

Stdlib-only (`html.parser.HTMLParser`), not a new dependency - a
repo-wide grep confirmed zero existing HTML-stripping utility and zero
`beautifulsoup4`/`html2text`/`lxml` dependency anywhere in this project;
this is a single call site, and Confluence's storage format is well-
behaved enough (a specific, documented XHTML subset, not arbitrary
attacker-controlled HTML from the open web) that a ~40-line parser
covers it without pulling in a real HTML parsing library.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Block-level elements get a paragraph break on close, so
# "<p>A</p><p>B</p>" reads as "A\n\nB", not "AB" - preserves the
# paragraph structure app.rag.chunking.chunk_text splits on.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse runs of horizontal whitespace, then collapse 3+ blank
        # lines down to one - mirrors app.rag.loaders.clean_text's own
        # whitespace normalization so both sources reach chunk_text in
        # the same shape.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Best-effort plaintext extraction - malformed/unclosed tags don't
    raise (HTMLParser tolerates them), they just may lose some paragraph
    breaks."""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()
