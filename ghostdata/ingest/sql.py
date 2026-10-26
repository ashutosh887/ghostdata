from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..dataset import parse_time
from ..observations import Evidence, Observation, Snapshot, identifier_keys, system_for
from .records import record_observation

HEADER_RE = re.compile(r"^-- (Captured at|Database topology): (.+)$", re.M)


def load(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(path.read_text(encoding="utf-8"))
    return con


def sql_evidence(file_id: str, captured_at: datetime, path: Path) -> Evidence:
    con = load(path)
    header = dict(HEADER_RE.findall(path.read_text(encoding="utf-8")[:2000]))
    snapshot_t = parse_time(header["Captured at"]) if "Captured at" in header else captured_at
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    scope = {}
    if "snapshot_scope" in tables:
        scope = {r["origin_system"]: parse_time(r["captured_at"]) for r in con.execute("SELECT * FROM snapshot_scope")}

    ev = Evidence()
    by_system: dict[str, set] = {}
    keys_in_file: set = set()
    for table in tables:
        if table == "snapshot_scope":
            continue
        for row in con.execute(f'SELECT * FROM "{table}"'):
            rec = dict(row)
            collection = rec.get("collection_name")
            if "record_json" in rec:
                rec = {**json.loads(rec["record_json"]), "updated_at": rec["updated_at"]}
            rid = rec["resource_id"]
            system = system_for(rid)
            if system is None:
                continue
            t = parse_time(rec["updated_at"]) if rec.get("updated_at") else snapshot_t
            obs = record_observation(file_id, captured_at, t, system, rid, rec, collection, f"{path.name} {table}")
            ev.observations.append(obs)
            by_system.setdefault(system, set()).add(rid)
            keys_in_file |= obs.keys

    if scope:
        for system, t in scope.items():
            ev.snapshots.append(Snapshot(file_id, captured_at, t, frozenset({system}),
                                         frozenset(by_system.get(system, ())), frozenset(keys_in_file),
                                         f"{path.name} scope {system}"))
    else:
        ev.snapshots.append(Snapshot(file_id, captured_at, snapshot_t, frozenset(by_system),
                                     frozenset(r for rs in by_system.values() for r in rs), frozenset(keys_in_file),
                                     f"{path.name} {header.get('Database topology', '')}".strip()))
    return ev
