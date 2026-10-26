from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .config import ablated
from .ingest.activity import Claim
from .observations import Observation, Snapshot

RISK_CHECKS = {
    "CHECK_DATA_FLOW": "remains enabled",
    "CHECK_RESTORE_ACCESS": "can still be restored",
}


@dataclass(frozen=True)
class Proof:
    """The source that shows a fact, and when."""

    source_id: str
    source_at: datetime
    t: datetime
    note: str


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    present: bool | None = None
    exposed: bool | None = None
    active: bool | None = None
    presence_proof: list[Proof] = field(default_factory=list)
    exposure_proof: list[Proof] = field(default_factory=list)
    activity_proof: list[Proof] = field(default_factory=list)
    trail: list[str] = field(default_factory=list)


def proof(o: Observation) -> Proof:
    return Proof(o.source_id, o.source_at, o.t, o.where)


def best_omission(snapshots: list[Snapshot], system_id: str, resource_id: str, keys: frozenset,
                  since: datetime, audit_at: datetime) -> tuple[Snapshot | None, bool]:
    """The most telling capture that covers the system and does not list the record."""
    usable = [s for s in snapshots
              if s.covers(system_id) and resource_id not in s.resources
              and s.source_at <= audit_at and since <= s.t <= audit_at]
    if not usable:
        return None, False
    best = max(usable, key=lambda s: (bool(s.keys & keys), bool(s.resources), s.t))
    return best, bool(best.keys & keys)


def latest(events: list[tuple[datetime, bool, Proof]]) -> tuple[bool | None, list[Proof]]:
    """Value at the newest time; at a tie, any True wins (one replica holding the row is enough).

    Proofs are every observation that agrees with that value since the last one that disagreed.
    """
    if not events:
        return None, []
    newest = max(t for t, _, _ in events)
    value = any(v for t, v, _ in events if t == newest)
    changed = max((t for t, v, _ in events if v != value and t < newest), default=None)
    return value, [p for t, v, p in events if v == value and (changed is None or t > changed)]


def state_at(resource_id: str, system_id: str, observations: list[Observation], snapshots: list[Snapshot],
             claims: list[Claim], keys: frozenset, reported_at: datetime, audit_at: datetime) -> ResourceState:
    st = ResourceState(resource_id, system_id)
    horizon = datetime.max.replace(tzinfo=audit_at.tzinfo) if ablated("no_time_filter") else audit_at
    seen = [o for o in observations if o.t <= horizon and o.kind != "link"]

    presence = [(o.t, o.present, proof(o)) for o in seen if o.present is not None]
    snap, linked = best_omission(snapshots, system_id, resource_id, keys, reported_at, audit_at)
    label = "linked" if linked else "unlinked"
    if snap is None and not presence:
        snap, linked = best_omission(snapshots, system_id, resource_id, keys, datetime.min.replace(tzinfo=audit_at.tzinfo), audit_at)
        label = "latest capture before the audit"
    if snap is not None and (linked or not presence):
        presence.append((snap.t, False, Proof(snap.source_id, snap.source_at, snap.t, f"not listed in {snap.where}")))
        st.trail.append(f"omission from {snap.source_id} ({label})")
    st.present, st.presence_proof = latest(presence)

    exposure = [(o.t, o.exposed, proof(o)) for o in seen if o.exposed is not None and o.present]
    st.exposed, st.exposure_proof = latest(exposure)

    activity = [(o.t, o.active, proof(o)) for o in seen if o.active is not None]
    if not activity:
        for c in claims:
            phrase = RISK_CHECKS.get(c.event_type)
            if phrase and phrase in c.details and c.t <= audit_at:
                activity.append((c.t, True, Proof(c.activity_id, c.t, c.t, c.event_type)))
    st.active, st.activity_proof = latest(activity)
    return st
