from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
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
    corpus.stats["activity"] = Counter(claims=len(corpus.claims), identity_links=len(links))
    return corpus
