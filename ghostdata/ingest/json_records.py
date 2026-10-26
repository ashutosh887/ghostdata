from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ..dataset import parse_time
from ..observations import Evidence, Snapshot, system_for
from .records import lookup_observation, record_observation

HANDOVER_RE = re.compile(
    r"^- (?P<ts>\S+Z) \| (?P<system>\w+) \| (?P<rid>\w+) \| (?P<cat>[A-Z_]+) \| (?P<result>[A-Z_]+) \| (?P<subject>.+)$"
)


def _lookups(ev: Evidence, file_id: str, captured_at: datetime, records: list, where: str, subject_key: str) -> None:
    for r in records:
        ev.observations.append(lookup_observation(
            file_id, captured_at, parse_time(r["recorded_at"]), r["system"], r["resource_id"], r["record_type"],
            r["result"], r.get(subject_key), where,
        ))


def _bundle(ev: Evidence, file_id: str, captured_at: datetime, data: dict, name: str) -> None:
    for snap in data["snapshots"]:
        t = parse_time(snap["captured_at"])
        where = f"{name} {snap['data_store']}/{snap['collection']}@{snap['captured_at']}"
        if snap["collection"] == "operational_record_history":
            _lookups(ev, file_id, captured_at, snap["records"], where, "lookup_value")
            continue
        rids, keys = set(), set()
        for rec in snap["records"]:
            rid = rec["resource_id"]
            obs = record_observation(file_id, captured_at, t, system_for(rid), rid, rec, snap["collection"], where)
            ev.observations.append(obs)
            rids.add(rid)
            keys |= obs.keys
        ev.snapshots.append(Snapshot(file_id, captured_at, t, frozenset({snap["data_store"]}), frozenset(rids),
                                     frozenset(keys), where))


def _service_export(ev: Evidence, file_id: str, captured_at: datetime, data: dict, name: str) -> None:
    for system, lists in data["service_exports"].items():
        for list_name, entries in lists.items():
            for e in entries:
                rec = dict(e)
                if "profile" in rec:
                    rec = {**(rec.pop("profile") or {}), **rec}
                if "hits" in rec:
                    docs = rec.pop("hits")["documents"]
                    rec = {**(docs[0] if docs else {}), **rec, "status_code": 200 if docs else 404}
                    rec.pop("query", None)
                ev.observations.append(record_observation(
                    file_id, captured_at, parse_time(e["observed_at"]), system, e["resource_id"], rec, list_name,
                    f"{name} {system}.{list_name}", kind="read",
                ))


def _collection(ev: Evidence, file_id: str, captured_at: datetime, data: dict, name: str) -> None:
    t = parse_time(data["captured_at"])
    for rec in data["records"]:
        rid = rec["resource_id"]
        ev.observations.append(record_observation(
            file_id, captured_at, t, system_for(rid), rid, rec, data["collection"], f"{name} {data['collection']}",
        ))


def json_evidence(file_id: str, captured_at: datetime, path: Path) -> Evidence:
    data = json.loads(path.read_text(encoding="utf-8"))
    ev = Evidence()
    if "snapshots" in data:
        _bundle(ev, file_id, captured_at, data, path.name)
    elif "service_exports" in data:
        _service_export(ev, file_id, captured_at, data, path.name)
    elif "records" in data and data["records"] and "record_type" in data["records"][0]:
        _lookups(ev, file_id, captured_at, data["records"], f"{path.name} {data.get('origin', '')}", "subject_reference")
    elif "collection" in data:
        _collection(ev, file_id, captured_at, data, path.name)
    else:
        raise ValueError(f"{file_id}: unknown JSON evidence shape {sorted(data)}")
    return ev


def text_evidence(file_id: str, captured_at: datetime, path: Path) -> Evidence:
    ev = Evidence()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = HANDOVER_RE.match(line.strip())
        if m:
            ev.observations.append(lookup_observation(
                file_id, captured_at, parse_time(m["ts"]), m["system"], m["rid"], m["cat"], m["result"],
                m["subject"], f"{path.name} handover",
            ))
    if not ev.observations:
        raise ValueError(f"{file_id}: no handover lines recognised")
    return ev
