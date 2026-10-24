from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..dataset import DATASET_DIR, parse_time, read_csv

from ..observations import Observation, Snapshot
from .activity import Claim, link_observations, load_claims
from .documents import Document, document_evidence, read_document
from .json_records import json_evidence, text_evidence
from .logs import log_observations
from .sql import sql_evidence


@dataclass
class Corpus:
    observations: list[Observation] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    documents: dict[str, Document] = field(default_factory=dict)
    files: dict[str, dict] = field(default_factory=dict)
    stats: dict[str, Counter] = field(default_factory=dict)


def load_corpus(dataset_dir: Path = DATASET_DIR) -> Corpus:
    corpus = Corpus()
    for row in read_csv(dataset_dir / "evidence_files.csv"):
        file_id, path = row["file_id"], dataset_dir / row["file_path"]
        captured_at = parse_time(row["captured_at"])
        corpus.files[file_id] = row
        suffix = path.suffix.lower()
        family = suffix.lstrip(".")
        stat = corpus.stats.setdefault(family, Counter())
        stat["files"] += 1
        if suffix == ".log":
            obs = log_observations(file_id, captured_at, path, stat)
            corpus.observations += obs
            continue
        if suffix == ".sql":
            ev = sql_evidence(file_id, captured_at, path)
        elif suffix == ".json":
            ev = json_evidence(file_id, captured_at, path)
        elif suffix == ".txt":
            ev = text_evidence(file_id, captured_at, path)
        elif suffix in (".pdf", ".png"):
            doc = read_document(file_id, captured_at, path)
            corpus.documents[file_id] = doc
            ev = document_evidence(doc)
        else:
            raise ValueError(f"{file_id}: no reader for {path.name}")
        corpus.observations += ev.observations
        corpus.snapshots += ev.snapshots
        stat["observations"] += len(ev.observations)
        stat["snapshots"] += len(ev.snapshots)

    corpus.claims = load_claims(dataset_dir / "system_activity.csv")
    links = link_observations(corpus.claims)
    corpus.observations += links
    shown = documents_for_links(links, corpus.documents)
    corpus.observations += shown
    corpus.stats["activity"] = Counter(claims=len(corpus.claims), identity_links=len(links), linked_documents=len(shown))
    return corpus


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def documents_for_links(links: list[Observation], documents: dict[str, Document]) -> list[Observation]:
    """A catalog link names a display reference; the newest earlier document showing it is about that record."""
    out = []
    for link in links:
        ref = link.where.split("ref=", 1)[1]
        shown = [d for d in documents.values() if d.captured_at <= link.t and _squash(ref) in _squash(d.text)]
        if not shown:
            continue
        doc = max(shown, key=lambda d: d.captured_at)
        out.append(replace(link, source_id=doc.file_id, source_at=doc.captured_at, t=doc.captured_at,
                           kind=doc.kind, present=True, where=f"{doc.kind} {doc.file_id} shows {ref}"))
    return out
