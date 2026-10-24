from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..observations import Evidence, Observation, identifier_keys, system_for

CACHE_DIR = Path(__file__).resolve().parents[2] / "cache" / "ocr"
LOOSE_ID_RE = re.compile(
    r"\b(account|search|analytics|support|export|backup|data[_ .]flow|audit[_ ]record|legal[_ ]hold|tombstone|"
    r"marketing|object)[_ .](\d{2,6})\b"
)
USER_ID_RE = re.compile(r"\buser_\d+\b")


@dataclass(frozen=True)
class Document:
    """Text pulled from a PDF or a screenshot, before any model reads it."""

    file_id: str
    captured_at: datetime
    kind: str
    text: str
    resource_ids: tuple
    keys: frozenset


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"{tool} is required to read evidence documents; install it and rerun")
    return path


def _cached(path: Path, tag: str, produce) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    cache = CACHE_DIR / f"{tag}-{digest}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = produce()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def pdf_text(path: Path) -> str:
    return _cached(path, "pdf", lambda: subprocess.run(
        [_require("pdftotext"), "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout)


def ocr_text(path: Path) -> str:
    return _cached(path, "ocr", lambda: subprocess.run(
        [_require("tesseract"), str(path), "-", "--psm", "3"], capture_output=True, text=True, check=True).stdout)


def resource_ids_in(text: str) -> tuple:
    found = []
    for prefix, number in LOOSE_ID_RE.findall(text):
        rid = re.sub(r"[ .]", "_", prefix) + "_" + number
        if rid not in found:
            found.append(rid)
    return tuple(found)


def read_document(file_id: str, captured_at: datetime, path: Path) -> Document:
    kind = "pdf" if path.suffix == ".pdf" else "image"
    text = pdf_text(path) if kind == "pdf" else ocr_text(path)
    keys = identifier_keys(text) | set(USER_ID_RE.findall(text))
    return Document(file_id, captured_at, kind, text, resource_ids_in(text), frozenset(keys))


def document_evidence(doc: Document) -> Evidence:
    """A document that shows a record is evidence the record existed when it was captured."""
    ev = Evidence()
    for rid in doc.resource_ids:
        system = system_for(rid)
        if system is None:
            continue
        ev.observations.append(Observation(
            source_id=doc.file_id,
            source_at=doc.captured_at,
            t=doc.captured_at,
            system_id=system,
            resource_id=rid,
            kind=doc.kind,
            present=True,
            attachment=doc.kind == "pdf" and system == "support_platform",
            keys=doc.keys if len(doc.resource_ids) == 1 else frozenset(),
            where=f"{doc.kind} {doc.file_id}",
        ))
    return ev
