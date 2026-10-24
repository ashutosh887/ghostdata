from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

from ..config import MODELS, PROMPT_DIR
from ..dataset import DATASET_DIR
from ..ingest import Corpus
from ..observations import Observation, identifier_keys
from .guard import fence, injection_hits
from .llm import ModelClient

TRI = {"type": "string", "enum": ["yes", "no", "not_shown"]}
SCHEMA = {
    "title": "document_reading",
    "type": "object",
    "properties": {
        "record_shown": {"type": "boolean"},
        "status_label": {"type": "string"},
        "names": {"type": "array", "items": {"type": "string"}},
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "stable_reference_only": {"type": "boolean"},
        "flow_enabled": TRI,
        "restore_allowed": TRI,
        "available": TRI,
        "notes": {"type": "string"},
    },
    "required": ["record_shown", "status_label", "names", "emails", "phones", "stable_reference_only",
                 "flow_enabled", "restore_allowed", "available", "notes"],
    "additionalProperties": False,
}
TRI_VALUE = {"yes": True, "no": False, "not_shown": None}


class DocumentReader:
    """The model reads what a screenshot or PDF shows; code turns the reading into an observation."""

    def __init__(self, client: ModelClient, model: str = MODELS["vision"], dataset_dir: Path = DATASET_DIR):
        self.client = client
        self.model = model
        self.dataset_dir = dataset_dir
        self.system = (PROMPT_DIR / "document.md").read_text(encoding="utf-8")
        self.readings: dict[tuple, dict] = {}
        self.flags: dict[str, list[str]] = {}
        self.contradicted: dict[str, tuple] = {}

    def read(self, corpus: Corpus, obs: Observation) -> dict:
        doc = corpus.documents[obs.source_id]
        ref = obs.where.rsplit("shows ", 1)[1]
        header = f"record: {obs.resource_id} (catalog reference: {ref})"
        if doc.kind == "image":
            path = self.dataset_dir / corpus.files[doc.file_id]["file_path"]
            data = base64.b64encode(path.read_bytes()).decode()
            user = [{"type": "text", "text": header},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}]
            hits = injection_hits(doc.text)
        else:
            user = f"{header}\n\n{fence('document', doc.text)}"
            hits = injection_hits(doc.text)
        if hits:
            self.flags[doc.file_id] = hits
        reading = self.client.json("vision", self.model, self.system, user, SCHEMA, max_tokens=600)
        self.readings[(doc.file_id, obs.resource_id)] = reading
        return reading

    def apply(self, corpus: Corpus) -> None:
        """Replace the bare 'document shows this record' observations with what the model read.

        A catalog link is a claim. If the document it points at shows only another person's identifiers,
        the link is dropped rather than deleting someone else's record.
        """
        updated = []
        contradicted = {}
        for o in corpus.observations:
            if o.kind not in ("image", "pdf") or "shows" not in o.where:
                updated.append(o)
                continue
            r = self.read(corpus, o)
            shown_ids = identifier_keys(r["emails"]) | identifier_keys(r["phones"])
            exposed = bool(r["names"] or r["emails"] or r["phones"]) and not r["stable_reference_only"]
            active = TRI_VALUE[r["flow_enabled"]]
            if active is None:
                active = TRI_VALUE[r["restore_allowed"]]
            present = r["record_shown"] and TRI_VALUE[r["available"]] is not False
            if shown_ids and not shown_ids & o.keys:
                contradicted[o.resource_id] = (o.source_id, o.keys)
                updated.append(replace(o, keys=frozenset(), present=present, exposed=exposed,
                                       where=f"{o.where}; shows {', '.join(sorted(shown_ids))}, not the linked subject"))
                continue
            updated.append(replace(
                o, present=present, exposed=exposed if present else None, active=active,
                keys=o.keys | frozenset(shown_ids),
                where=f"{o.where}; model read: {r['status_label'] or 'no label'}"
                      f"{'; ' + r['notes'] if r['notes'] else ''}",
            ))
        corpus.observations = [
            replace(o, keys=frozenset(), where=f"{o.where} (contradicted by {contradicted[o.resource_id][0]})")
            if o.kind == "link" and o.resource_id in contradicted else o
            for o in updated
        ]
        self.contradicted = contradicted
