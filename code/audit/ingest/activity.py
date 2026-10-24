from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..dataset import parse_time, read_csv
from ..observations import RESOURCE_RE, Observation, identifier_keys, system_for

LINK_RE = re.compile(r"^Data catalog linked (?P<rid>\w+) \((?P<ref>[^)]+)\) to (?P<email>\S+) and (?P<user>user_\d+)\.$")
OBJECT_LINK_RE = re.compile(r"confirmed (?P<rid>\w+) \((?P<ref>[^)]+)\) belongs only to (?P<email>\S+) and (?P<user>user_\d+)")


@dataclass(frozen=True)
class Claim:
    """A row of system_activity.csv. It says an operation ran and what it reported; it proves no final state."""

    activity_id: str
    t: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    result: str
    details: str
    mentions: tuple


def load_claims(path: Path) -> list[Claim]:
    claims = []
    for r in read_csv(path):
        mentions = tuple(m.group(0) for m in RESOURCE_RE.finditer(r["details"]) if m.group(0) != r["resource_id"])
        claims.append(Claim(r["activity_id"], parse_time(r["event_time"]), r["event_type"], r["source_system"],
                            r["target_system"], r["resource_id"], r["reported_result"], r["details"], mentions))
    return claims


def link_observations(claims: list[Claim]) -> list[Observation]:
    """Catalog rows that tie a resource shown in a screenshot or PDF to a user."""
    out = []
    for c in claims:
        if c.event_type != "LINK_RESOURCE_IDENTITY":
            continue
        m = LINK_RE.match(c.details) or OBJECT_LINK_RE.search(c.details)
        if not m:
            raise ValueError(f"{c.activity_id}: unrecognised identity link: {c.details}")
        out.append(Observation(
            source_id=c.activity_id,
            source_at=c.t,
            t=c.t,
            system_id=system_for(m["rid"]),
            resource_id=m["rid"],
            kind="link",
            keys=frozenset(identifier_keys([m["email"], m["user"]])),
            where=f"catalog link {m['ref']}",
        ))
    return out
