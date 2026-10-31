from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup


WHITESPACE_PATTERN = re.compile(r"\s+")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+", re.MULTILINE)


def clean_cell_text(value: str) -> str:
    """Collapse internal whitespace so equivalent cells normalize identically."""
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def rectangularize(grid: Iterable[Iterable[str]]) -> list[list[str]]:
    rows = [list(row) for row in grid]
    if not rows:
        return []

    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def parse_html_table(html_str: str) -> list[list[str]]:
    """
    Expand an HTML table into a rectangular grid, preserving rowspan/colspan layout.
    """
    soup = BeautifulSoup(html_str, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = table.find_all("tr")
    occupied: dict[tuple[int, int], str] = {}

    for row_index, row in enumerate(rows):
        column_index = 0
        for cell in row.find_all(["td", "th"]):
            while (row_index, column_index) in occupied:
                column_index += 1

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            value = clean_cell_text(cell.get_text(" ", strip=True))

            for row_offset in range(rowspan):
                for column_offset in range(colspan):
                    occupied[(row_index + row_offset, column_index + column_offset)] = value

            column_index += colspan

    if not occupied:
        return []

    max_row = max(row for row, _ in occupied) + 1
    max_col = max(col for _, col in occupied) + 1
    grid = [
        [occupied.get((row_index, col_index), "") for col_index in range(max_col)]
        for row_index in range(max_row)
    ]
    return rectangularize(grid)



def _update_active_headings(active_headings: list[str], text: str) -> list[str]:
    """
    Scan *text* for markdown headings and maintain a heading stack.
    When a heading at level N appears, all headings at level >= N are replaced.
    """
    updated = list(active_headings)
    for line in text.split("\n"):
        m = HEADING_PATTERN.match(line.strip())
        if m:
            level = len(m.group(1))
            updated = [
                h for h in updated
                if len(HEADING_PATTERN.match(h.strip()).group(1)) < level
            ]
            updated.append(line.strip())
    return updated


def _strip_heading_lines(text: str) -> str:
    """Remove markdown heading lines from *text* so they are not duplicated."""
    return "\n".join(
        line for line in text.split("\n")
        if not HEADING_PATTERN.match(line.strip())
    ).strip()


def parse_bundles_from_md(md_path: str | Path) -> list[dict]:
    """
    Extracts bundles of (context, table_grid) from a markdown file.

    Uses section-aware context propagation:
      - Markdown headings are tracked as "active" and persist across tables
        until a heading at the same or higher level replaces them.
      - For consecutive tables with no text between them, the most recent
        non-empty text block is carried forward.
      - Each bundle's context = active headings + body text (deduplicated).
    """
    content = Path(md_path).read_text(encoding="utf-8")
    parts = re.split(r"(<table\b.*?</table>)", content, flags=re.DOTALL | re.IGNORECASE)

    bundles = []
    active_headings: list[str] = []   # "sticky" section headings
    last_body_text = ""               # most recent non-empty body text between tables
    pending_text = ""                 # raw text immediately before the current table

    for part in parts:
        if part.strip().lower().startswith("<table"):
            grid = parse_html_table(part)
            if grid:
                if pending_text.strip():
                    active_headings = _update_active_headings(active_headings, pending_text)
                    body = _strip_heading_lines(pending_text)
                    if body:
                        last_body_text = body

                heading_block = "\n".join(active_headings)
                if heading_block:
                    full_context = heading_block + "\n\n" + last_body_text
                else:
                    full_context = last_body_text

                bundles.append({
                    "context": full_context.strip(),
                    "table": grid,
                    "raw_html": part
                })
            pending_text = ""
        else:
            pending_text = part

    try:
        md_path_obj = Path(md_path)
        content_list_path = md_path_obj.parent / f"{md_path_obj.stem}_content_list.json"
        if content_list_path.exists():
            with open(content_list_path, "r", encoding="utf-8") as f:
                content_list = json.load(f)
            table_items = [item for item in content_list if item.get("type") == "table"]
            # Match by the table's HTML: MinerU writes table_body into the .md verbatim,
            # and tables that parse to an empty grid are dropped from bundles, so
            # matching by position breaks as soon as one table is skipped.
            pages_by_html = {
                WHITESPACE_PATTERN.sub("", item.get("table_body") or ""): item.get("page_idx")
                for item in table_items
                if item.get("table_body")
            }
            for i, bundle in enumerate(bundles):
                page_idx = pages_by_html.get(WHITESPACE_PATTERN.sub("", bundle["raw_html"]))
                if page_idx is None and len(table_items) == len(bundles):
                    page_idx = table_items[i].get("page_idx")
                if page_idx is not None:
                    bundle["page_idx"] = page_idx
    except (OSError, ValueError) as e:
        print(f"[WARN] Could not read page numbers for tables in {md_path}: {e}")

    return bundles


TEXT_CHUNK_MAX_CHARS = 1200
SKIPPED_BLOCK_TYPES = {"header", "footer", "page_number", "page_footnote", "table", "equation"}


def _block_text(item: dict) -> str:
    """Readable text of one MinerU content_list block (text, list or figure caption)."""
    block_type = item.get("type")
    if block_type == "text":
        return clean_cell_text(item.get("text", ""))
    if block_type == "list":
        return "\n".join(f"- {clean_cell_text(x)}" for x in item.get("list_items", []) if x)
    if block_type == "image":
        caption = " ".join(item.get("image_caption") or item.get("img_caption") or [])
        return f"[Figure] {clean_cell_text(caption)}" if caption.strip() else ""
    return ""


def parse_text_chunks(md_path: str | Path) -> list[dict]:
    """
    Split the prose of a MinerU document into section-sized chunks.

    Manuals keep most of their procedures, warnings and button descriptions in
    plain text rather than tables, so these chunks sit in the same index as the
    table bundles. Each chunk carries its section heading and the page it starts
    on (from MinerU's content_list.json) so answers can cite a page.
    """
    md_path = Path(md_path)
    content_list_path = md_path.parent / f"{md_path.stem}_content_list.json"
    if not content_list_path.exists():
        return _text_chunks_from_markdown(md_path)

    with open(content_list_path, "r", encoding="utf-8") as f:
        content_list = json.load(f)

    chunks: list[dict] = []
    section = ""
    buffer: list[str] = []
    buffer_len = 0
    buffer_page = None

    def flush():
        nonlocal buffer, buffer_len, buffer_page
        body = "\n".join(buffer).strip()
        if body:
            chunks.append({"section": section, "text": body, "page_idx": buffer_page})
        buffer, buffer_len, buffer_page = [], 0, None

    for item in content_list:
        if item.get("type") in SKIPPED_BLOCK_TYPES:
            continue
        if item.get("type") == "text" and item.get("text_level"):
            flush()
            section = clean_cell_text(item.get("text", ""))
            continue
        text = _block_text(item)
        if not text:
            continue
        if buffer and buffer_len + len(text) > TEXT_CHUNK_MAX_CHARS:
            flush()
        if buffer_page is None:
            buffer_page = item.get("page_idx")
        buffer.append(text)
        buffer_len += len(text)
    flush()
    return chunks


def _text_chunks_from_markdown(md_path: Path) -> list[dict]:
    """Fallback for plain Markdown input without MinerU page data."""
    content = re.sub(r"<table\b.*?</table>", "", md_path.read_text(encoding="utf-8"),
                     flags=re.DOTALL | re.IGNORECASE)
    chunks: list[dict] = []
    section = ""
    for block in re.split(r"\n\s*\n", content):
        block = block.strip()
        if not block:
            continue
        if HEADING_PATTERN.match(block) and "\n" not in block:
            section = HEADING_PATTERN.sub("", block).strip()
            continue
        if chunks and chunks[-1]["section"] == section and \
                len(chunks[-1]["text"]) + len(block) <= TEXT_CHUNK_MAX_CHARS:
            chunks[-1]["text"] += "\n" + block
        else:
            chunks.append({"section": section, "text": block, "page_idx": None})
    return chunks

