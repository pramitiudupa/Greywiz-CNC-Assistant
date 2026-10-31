"""
Small JSON-file stores for the demo: the shop's one CNC machine profile and
the problem reports (cases) workers submit against it.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("data")
MACHINE_FILE = DATA_DIR / "machine.json"
CASES_DIR = DATA_DIR / "cases"

MACHINE_FIELDS = ("name", "maker", "model", "controller", "location", "notes")
CASE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
WORD_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "the", "a", "an", "is", "it", "not", "and", "or", "of", "to", "in", "on", "my",
    "this", "that", "when", "with", "machine", "working", "does", "doesn", "t", "i",
}


def load_machine() -> dict | None:
    if not MACHINE_FILE.exists():
        return None
    return json.loads(MACHINE_FILE.read_text(encoding="utf-8"))


def save_machine(data: dict) -> dict:
    machine = {field: str(data.get(field) or "").strip() for field in MACHINE_FIELDS}
    if not machine["name"]:
        raise ValueError("Machine name is required.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MACHINE_FILE.write_text(json.dumps(machine, indent=2), encoding="utf-8")
    return machine


def _case_path(case_id: str) -> Path:
    if not CASE_ID_PATTERN.match(case_id):
        raise ValueError("Invalid case id.")
    return CASES_DIR / f"{case_id}.json"


def create_case(description: str, photo: bytes | None, photo_ext: str, result: dict) -> dict:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    case_id = uuid.uuid4().hex
    photo_name = None
    if photo:
        photo_name = f"{case_id}{photo_ext}"
        (CASES_DIR / photo_name).write_bytes(photo)
    case = {
        "id": case_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "photo": photo_name,
        "status": "open",
        "fix_note": "",
        "result": result,
    }
    _case_path(case_id).write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    return case


def get_case(case_id: str) -> dict | None:
    path = _case_path(case_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def photo_path(case: dict) -> Path | None:
    if not case.get("photo"):
        return None
    path = CASES_DIR / case["photo"]
    return path if path.exists() else None


def update_case(case_id: str, status: str, fix_note: str) -> dict:
    case = get_case(case_id)
    if case is None:
        raise KeyError(case_id)
    if status not in ("open", "fixed"):
        raise ValueError("Status must be 'open' or 'fixed'.")
    case["status"] = status
    case["fix_note"] = fix_note.strip()
    case["updated_at"] = datetime.now(timezone.utc).isoformat()
    _case_path(case_id).write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    return case


def list_cases() -> list[dict]:
    if not CASES_DIR.exists():
        return []
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in CASES_DIR.glob("*.json")]
    return sorted(cases, key=lambda c: c["created_at"], reverse=True)


def _words(text: str) -> set[str]:
    return {w for w in WORD_PATTERN.findall(text.lower()) if w not in STOP_WORDS and len(w) > 2}


def similar_fixed_cases(query: str, limit: int = 2) -> list[dict]:
    """Past problems on this machine that were marked fixed, ranked by shared words."""
    query_words = _words(query)
    if not query_words:
        return []
    scored = []
    for case in list_cases():
        if case["status"] != "fixed" or not case.get("fix_note"):
            continue
        result = case.get("result") or {}
        case_text = " ".join([
            case.get("description", ""),
            result.get("photo_reading", {}).get("part_shown", ""),
            result.get("likely_cause", {}).get("title", ""),
        ])
        overlap = len(query_words & _words(case_text))
        if overlap >= 2:
            scored.append((overlap, case))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [case for _, case in scored[:limit]]
