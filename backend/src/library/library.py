"""
Document library checks for the shop's CNC machine.

Companies rarely have every document for a machine: the operator manual is
there, but the alarm list or maintenance schedule is missing. This module

  1. works out which kinds of document a CNC machine needs and which of them
     the uploaded documents already cover (keyword evidence from the indexed
     text, no AI call needed),
  2. collects references inside the documents to other manuals
     ("refer to the Service Manual"),
  3. offers missing documents only from a fixed catalog of validated, official
     sources (the machine maker's own site), and
  4. downloads one only after the user consents, recording who agreed, when,
     and where it came from.
"""

from __future__ import annotations

import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader, PdfWriter

DATA_DIR = Path("data")
SOURCES_FILE = DATA_DIR / "library_sources.json"
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024

# What a CNC machine's document set should contain, and the words that show a
# document covers it. A kind counts as covered when the evidence passes `need`
# and, where given, at least one `must` pattern appears (passing mentions of
# "lubricate" do not make an operator manual a maintenance schedule).
EXPECTED_KINDS = {
    "operator": {
        "label": "Operator's manual",
        "why": "how to run the machine, what each button does, start-up and shut-down",
        "patterns": [r"cycle start", r"control pendant", r"power[- ]on", r"emergency stop", r"jog"],
        "need": 8,
    },
    "alarms": {
        "label": "Alarm list",
        "why": "what each alarm number on the screen means and how to clear it",
        "patterns": [r"\balarm\s*#?\s*\d{2,4}\b", r"\b\d{3,4}\s+[A-Z][A-Z ]{6,}\b"],
        "must": [r"\balarm\s*#?\s*\d{2,4}\b"],
        "need": 10,
    },
    "troubleshooting": {
        "label": "Troubleshooting / service guide",
        "why": "symptom-to-cause tables a technician uses to find the faulty part",
        "patterns": [r"troubleshoot", r"possible cause", r"symptom", r"corrective action", r"check (?:the|for)\b"],
        "need": 8,
    },
    "maintenance": {
        "label": "Maintenance schedule",
        "why": "which checks are due daily, weekly and every N hours",
        "patterns": [r"maintenance schedule", r"lubricat", r"\bevery \d+ (?:hours|months|days)", r"\b(?:daily|weekly|monthly)\b"],
        "must": [r"maintenance schedule", r"maintenance interval", r"\bevery \d+ (?:hours|months|days)"],
        "need": 6,
    },
    "electrical": {
        "label": "Electrical diagrams",
        "why": "wiring, fuses and boards, needed by an electrician",
        "patterns": [r"wiring diagram", r"schematic", r"\bfuse\b", r"\bpcb\b", r"connector"],
        "need": 8,
    },
}

REFERENCE_PATTERN = re.compile(
    r"(?:refer to|see|consult|described in)\s+(?:the\s+)?"
    r"((?:[A-Z][\w'/-]*\s){0,5}(?:Manual|Guide|Schedule|List|Diagrams?|Supplement))",
)

# Validated sources: official documents on the machine maker's own website.
# Only these can be suggested or downloaded; arbitrary URLs never are.
CATALOG = [
    {
        "id": "haas-vf-service-1996",
        "maker": "haas",
        "title": "Haas VF Series Service Manual - Troubleshooting, Alarms & Maintenance",
        "publisher": "Haas Automation (official)",
        "url": "https://haascnc.com/content/dam/haascnc/en/service/manual/service/english---vf-series-service-manual---1996.pdf",
        "allowed_domains": ["haascnc.com"],
        "pages": "2-41,200-203",
        "covers": ["troubleshooting", "alarms", "maintenance"],
        "edition_note": "Official Haas archive edition (1996). Alarm numbers and screens can differ on newer controls such as NGC.",
        "est_minutes": 6,
    },
    {
        "id": "haas-mill-maintenance-1993",
        "maker": "haas",
        "title": "Haas Mill Maintenance Manual - Troubleshooting & Lubrication",
        "publisher": "Haas Automation (official)",
        "url": "https://www.haascnc.com/content/dam/haascnc/en/service/manual/operator/english---mill-maintenance---operator's-manual---1993.pdf",
        "allowed_domains": ["haascnc.com"],
        "pages": "1-60",
        "covers": ["maintenance", "troubleshooting", "electrical"],
        "edition_note": "Official Haas archive edition (1993). Check intervals against your machine's current manual.",
        "est_minutes": 8,
    },
    {
        "id": "haas-mill-operator-ngc-2020",
        "maker": "haas",
        "title": "Haas Mill Operator's Manual (Next Generation Control) - Safety, Pendant, Operation",
        "publisher": "Haas Automation (official)",
        "url": "https://www.haascnc.com/content/dam/haascnc/en/service/manual/operator/english---mill-ngc---operator's-manual---2020.pdf",
        "allowed_domains": ["haascnc.com"],
        "pages": "23-32,45-50,58-78,125-126,165-174,194-195",
        "covers": ["operator"],
        "edition_note": "Official Haas manual, revision N (2020), for NGC-control mills.",
        "est_minutes": 7,
    },
]


# ── Provenance ───────────────────────────────────────────────────────────

def _load_sources() -> dict:
    if not SOURCES_FILE.exists():
        return {}
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))


def source_of(doc_name: str) -> dict | None:
    """Where an added document came from and who agreed to add it (None if uploaded)."""
    return _load_sources().get(doc_name)


def _record_source(doc_name: str, entry: dict, consented_by: str):
    sources = _load_sources()
    sources[doc_name] = {
        "catalog_id": entry["id"],
        "publisher": entry["publisher"],
        "url": entry["url"],
        "pages": entry["pages"],
        "edition_note": entry["edition_note"],
        "consented_by": consented_by or "unnamed user",
        "consented_at": datetime.now(timezone.utc).isoformat(),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(json.dumps(sources, indent=2), encoding="utf-8")


# ── Gap analysis ─────────────────────────────────────────────────────────

def _document_texts(output_base: Path) -> dict[str, str]:
    """Indexed text of each processed document (the BM25 sidecar written at indexing)."""
    texts = {}
    if not output_base.exists():
        return texts
    for doc_dir in sorted(output_base.iterdir()):
        sidecar = doc_dir / "faiss_index" / "bm25_documents.json"
        if sidecar.exists():
            chunks = json.loads(sidecar.read_text(encoding="utf-8"))
            texts[doc_dir.name] = "\n".join(c["page_content"] for c in chunks)
    return texts


def _kind_scores(text: str) -> dict[str, int]:
    scores = {}
    for kind, spec in EXPECTED_KINDS.items():
        must = spec.get("must")
        if must and not any(re.search(p, text, flags=re.IGNORECASE) for p in must):
            scores[kind] = 0
            continue
        scores[kind] = sum(len(re.findall(p, text, flags=re.IGNORECASE)) for p in spec["patterns"])
    return scores


def _maker_key(machine: dict | None) -> str:
    return (machine or {}).get("maker", "").strip().lower()


TITLE_WORD = re.compile(r"[a-z]{3,}")


def _looks_already_uploaded(title: str, doc_names) -> bool:
    """True when an uploaded document shares most of the catalog title's words
    (the owner uploaded their own copy of the same manual)."""
    wanted = set(TITLE_WORD.findall(title.lower()))
    return any(len(wanted & set(TITLE_WORD.findall(name.lower()))) >= 5 for name in doc_names)


def check_library(output_base: Path, machine: dict | None) -> dict:
    texts = _document_texts(output_base)
    added_ids = {s["catalog_id"] for s in _load_sources().values()}

    documents, covered = [], {}
    references: Counter = Counter()
    for doc_name, text in texts.items():
        scores = _kind_scores(text)
        kinds = [k for k, v in scores.items() if v >= EXPECTED_KINDS[k]["need"]]
        documents.append({"id": doc_name, "covers": kinds})
        for kind in kinds:
            covered.setdefault(kind, []).append(doc_name)
        references.update(m.strip() for m in REFERENCE_PATTERN.findall(text))

    maker = _maker_key(machine)
    missing = []
    for kind, spec in EXPECTED_KINDS.items():
        if kind in covered:
            continue
        suggestions = [
            {k: e[k] for k in ("id", "title", "publisher", "url", "pages", "edition_note", "est_minutes")}
            | {"domain": urlparse(e["url"]).hostname}
            for e in CATALOG
            if e["maker"] == maker and kind in e["covers"] and e["id"] not in added_ids
        ]
        missing.append({
            "kind": kind,
            "label": spec["label"],
            "why": spec["why"],
            "suggestions": suggestions,
        })

    suggested = {s["id"] for m in missing for s in m["suggestions"]}
    also_available = [
        {k: e[k] for k in ("id", "title", "publisher", "url", "pages", "edition_note", "est_minutes")}
        | {"domain": urlparse(e["url"]).hostname}
        for e in CATALOG
        if e["maker"] == maker and e["id"] not in added_ids and e["id"] not in suggested
        and not _looks_already_uploaded(e["title"], texts.keys())
    ]

    return {
        "also_available": also_available,
        "machine_maker": machine.get("maker") if machine else None,
        "documents": documents,
        "covered": [{"kind": k, "label": EXPECTED_KINDS[k]["label"], "documents": v} for k, v in covered.items()],
        "missing": missing,
        "references": [{"name": name, "count": n} for name, n in references.most_common(6)],
        "has_trusted_sources": any(e["maker"] == maker for e in CATALOG),
    }


# ── Consent-gated download ───────────────────────────────────────────────

def catalog_entry(catalog_id: str) -> dict:
    for entry in CATALOG:
        if entry["id"] == catalog_id:
            return entry
    raise KeyError(catalog_id)


def _page_numbers(spec: str, total: int) -> list[int]:
    pages = []
    for part in spec.split(","):
        start, _, end = part.partition("-")
        pages.extend(range(int(start), int(end or start) + 1))
    return [p - 1 for p in pages if 1 <= p <= total]


def _domain_allowed(url: str, allowed: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def fetch_document(catalog_id: str, consent: bool, consented_by: str, pdfs_dir: Path, safe_stem) -> tuple[str, Path]:
    """
    Download a catalog document after explicit consent, keep only its relevant
    pages, and save it as a PDF ready for processing. Returns (doc_name, path).
    """
    if not consent:
        raise PermissionError("The user has not agreed to add this document.")
    entry = catalog_entry(catalog_id)

    response = requests.get(entry["url"], timeout=120, stream=True, headers={"User-Agent": "Greywiz/1.0"})
    response.raise_for_status()
    if not _domain_allowed(response.url, entry["allowed_domains"]):
        raise ValueError(f"Download was redirected to an unapproved site ({urlparse(response.url).hostname}).")
    body = io.BytesIO()
    for block in response.iter_content(1 << 20):
        body.write(block)
        if body.tell() > MAX_DOWNLOAD_BYTES:
            raise ValueError("The document is larger than the 150 MB limit.")
    raw = body.getvalue()
    if not raw.startswith(b"%PDF"):
        raise ValueError("The source did not return a PDF file.")

    reader = PdfReader(io.BytesIO(raw))
    writer = PdfWriter()
    for index in _page_numbers(entry["pages"], len(reader.pages)):
        writer.add_page(reader.pages[index])
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)

    doc_name = safe_stem(entry["title"] + ".pdf")
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    path = pdfs_dir / f"{doc_name}.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    _record_source(doc_name, entry, consented_by)
    return doc_name, path
