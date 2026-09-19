"""Text extraction for uploaded knowledge-base files (spec: help-desk-kit-
style KB upload) - .md/.txt are decoded directly; .pdf/.docx go through
pypdf/python-docx first. Every extractor returns plain text ready for
`app.rag.loaders.clean_text` and the same chunk/embed/store pipeline
(`app.rag.ingest.ingest_documents`) regardless of source format - callers
never need to know which library produced the text.

Both libraries are pure-Python (no system binary like poppler/libreoffice
required), matching this project's "no new system dependency" bar for
Docker - verified directly against the installed packages (pypdf 6.19,
python-docx 1.2) before writing this, not assumed from documentation.
"""

from __future__ import annotations

import io

import pypdf
from docx import Document as DocxDocument

SUPPORTED_UPLOAD_EXTENSIONS = (".md", ".markdown", ".txt", ".pdf", ".docx")


class FileExtractionError(ValueError):
    """Raised for a file that matches a supported extension but can't
    actually be parsed (corrupt, encrypted, wrong format despite its
    extension, etc.) - callers turn this into a 400, never a 500."""


def extract_text(filename: str, raw: bytes) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("md", "markdown", "txt"):
        return _extract_plain_text(raw)
    if ext == "pdf":
        return _extract_pdf_text(raw)
    if ext == "docx":
        return _extract_docx_text(raw)
    raise FileExtractionError(f"Unsupported file extension: .{ext}")


def _extract_plain_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileExtractionError("File must be UTF-8 encoded text") from exc


def _extract_pdf_text(raw: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise FileExtractionError("Encrypted/password-protected PDFs are not supported")
        pages = [page.extract_text() or "" for page in reader.pages]
    except FileExtractionError:
        raise
    except pypdf.errors.PyPdfError as exc:
        raise FileExtractionError(f"Could not read this PDF: {exc}") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise FileExtractionError(
            "No extractable text found in this PDF - it may be a scanned "
            "image with no text layer (OCR is not supported)"
        )
    return text


# python-docx paragraph style names look like "Heading 1".."Heading 9" -
# converted to markdown "#".."#########" so the same heading structure
# survives into the plain-text article body shown in the KB reader.
def _heading_prefix(style_name: str) -> str | None:
    if not style_name.startswith("Heading "):
        return None
    level = style_name.removeprefix("Heading ").strip()
    if not level.isdigit():
        return None
    return "#" * min(int(level), 9)


def _extract_docx_text(raw: bytes) -> str:
    try:
        document = DocxDocument(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 - python-docx has no single base exception
        raise FileExtractionError(f"Could not read this Word document: {exc}") from exc

    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        prefix = _heading_prefix(paragraph.style.name if paragraph.style else "")
        blocks.append(f"{prefix} {text}" if prefix else text)

    for table in document.tables:
        rendered = _render_table_as_markdown(table)
        if rendered:
            blocks.append(rendered)

    text = "\n\n".join(blocks)
    if not text:
        raise FileExtractionError("No extractable text found in this Word document")
    return text


def _render_table_as_markdown(table) -> str:  # noqa: ANN001 - docx.table.Table, not worth importing for a type hint
    """A GFM pipe table (header row + `---` separator + data rows), not
    just `cell | cell` text - so it actually renders as a table wherever
    the extracted markdown is displayed, not just visually resembles one
    in a monospace preformatted block."""
    rows = [[cell.text.strip().replace("|", "\\|") for cell in row.cells] for row in table.rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    header, *data_rows = rows
    width = len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in data_rows:
        # A ragged row (docx allows merged cells to shorten .cells) is
        # padded rather than dropped, so one odd row doesn't break the
        # whole table's column alignment for every row after it.
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded[:width]) + " |")
    return "\n".join(lines)
