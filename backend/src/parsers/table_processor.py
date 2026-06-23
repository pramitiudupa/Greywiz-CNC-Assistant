from __future__ import annotations

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

    return bundles

