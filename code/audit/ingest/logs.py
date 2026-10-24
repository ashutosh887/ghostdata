from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..dataset import parse_time
from ..observations import (RESULT_STATE, Observation, has_direct_identifier, has_reference, identifier_keys,
                            is_set, system_for, truthy)

TS = r"(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) "
GRAMMARS = (
    ("bracket", re.compile(TS + r"\[(?P<level>\w+)\] \[(?P<service>[^\]]+)\] \[(?P<trace>[^\]]+)\] (?P<event>\w+): (?P<kv>.*)$")),
    ("pipe", re.compile(TS + r"\| (?P<level>\w+) \| (?P<service>\S+) \| (?P<trace>\S+) \| (?P<event>\w+) \| (?P<kv>.*)$")),
    ("json", re.compile(TS + r"(?P<json>\{.*\})$")),
    ("syslog", re.compile(TS + r"<\d+>1 \S+ (?P<service>\S+) (?P<trace>\S+) - - (?P<kv>.*)$")),
    ("cloud", re.compile(TS + r"requestId=(?P<trace>\S+) level=(?P<level>\w+) function=(?P<service>\S+) message=\"(?P<msg>.*)\"$")),
    ("levelfirst", re.compile(TS + r"(?P<level>[A-Z]+) (?P<kv>service=.*)$")),
    ("kv", re.compile(TS + r"(?P<kv>level=.*)$")),
)
KV_RE = re.compile(r'(\w+)=("((?:[^"\\]|\\.)*)"|\S+)')

NOISE_EVENTS = {"connection_acquired", "cache_lookup", "dependency_retry", "dependency_recovered"}


def parse_kv(text: str) -> dict:
    out = {}
    for key, raw, quoted in KV_RE.findall(text):
        value = quoted.replace('\\"', '"') if raw.startswith('"') else raw
        out[key] = None if value == "null" else value
    return out


@dataclass
class LogLine:
    file_id: str
    line_no: int
    t: datetime
    service: str
    trace: str | None
    event: str
    fields: dict


def parse_line(file_id: str, line_no: int, line: str) -> LogLine:
    for name, rx in GRAMMARS:
        m = rx.match(line)
        if not m:
            continue
        g = m.groupdict()
        if name == "json":
            fields = {k: (None if v == "null" else v) for k, v in json.loads(g["json"]).items()}
        elif name == "cloud":
            fields = parse_kv(g["msg"].replace('\\"', '"'))
        else:
            fields = parse_kv(g["kv"])
        service = g.get("service") or fields.get("service") or ""
        trace = g.get("trace") or fields.get("trace_id")
        event = g.get("event") or fields.get("event") or ""
        return LogLine(file_id, line_no, parse_time(g["ts"]), service, trace, event, fields)
    raise ValueError(f"{file_id} line {line_no}: no grammar matches: {line[:120]}")


def read_log(file_id: str, path: Path) -> list[LogLine]:
    lines = []
    with open(path, encoding="utf-8") as f:
        for no, raw in enumerate(f, start=1):
            raw = raw.rstrip("\n")
            if raw.strip():
                lines.append(parse_line(file_id, no, raw))
    return lines


def join_traces(lines: list[LogLine]) -> list[list[LogLine]]:
    """Group lines that share a trace id; lines without one stand alone."""
    groups: dict[str, list[LogLine]] = {}
    singles = []
    for ln in lines:
        if ln.event in NOISE_EVENTS:
            continue
        if ln.trace and ln.trace.startswith(("tr-", "rb-")):
            groups.setdefault(ln.trace, []).append(ln)
        else:
            singles.append([ln])
    return list(groups.values()) + singles


def _state(event: str, f: dict) -> dict | None:
    if event == "record_lookup":
        return RESULT_STATE.get(f.get("result"))
    if event in ("profile_lookup_completed", "contact_query_completed", "audit_record_read_completed"):
        found = f.get("rows") == "1" or f.get("http_status") == "200"
        return dict(present=found, exposed=found or None)
    if event == "deletion_marker_check":
        return dict(present=f.get("marker_found") == "false")
    if event == "index_query_completed":
        return dict(present=f.get("result") == "hit")
    if event in ("analytics_identity_scan", "message_pii_scan", "contact_lookup_completed"):
        return dict(present=True, exposed=True)
    if event == "attachment_pii_scan":
        return dict(present=True, exposed=True, attachment=True)
    if event == "analytics_profile_read":
        return dict(present=True, exposed=f.get("direct_identifiers") != "0")
    if event == "message_read":
        return dict(present=True, exposed=has_direct_identifier(f) or f.get("message_text") not in ("[REDACTED]", None))
    if event in ("analytics_profile_read_completed",):
        return dict(present=True, exposed=has_direct_identifier(f) or is_set(f.get("customer_reference")))
    if event == "support_ticket_read_completed":
        return dict(present=True, exposed=has_direct_identifier(f))
    if event == "restore_candidate_evaluated":
        return dict(present=True, active=f.get("eligible") == "true" and f.get("deletion_block") == "false")
    if event == "restore_authorization_completed":
        return dict(present=True, active=f.get("decision") != "deny")
    if event == "restore_policy_read_completed":
        return dict(present=truthy(f.get("archive_present")) is not False, active=truthy(f.get("restore_allowed")))
    if event in ("connector_heartbeat", "connector_config_loaded", "connector_config_read_completed"):
        return dict(present=True, active=truthy(f.get("enabled")))
    if event in ("export_download_check_completed", "export_metadata_read_completed"):
        return dict(present=truthy(f.get("available")) is not False)
    if event == "retained_order_loaded":
        return dict(present=True)
    return None


SERVICE_ALIASES = {"support_replica": "support_platform"}


def log_observations(file_id: str, captured_at: datetime, path: Path, stats: dict | None = None) -> list[Observation]:
    stats = stats if stats is not None else {}
    out = []
    for group in join_traces(read_log(file_id, path)):
        merged: dict = {}
        state = None
        when = None
        events = []
        for ln in group:
            merged.update(ln.fields)
            s = _state(ln.event, ln.fields)
            if s is not None:
                state = {**(state or {}), **s}
                when = ln.t
                events.append(ln.event)
        rid = merged.get("resource_id")
        if state is None or not rid:
            continue
        service = SERVICE_ALIASES.get(group[0].service, group[0].service)
        system = merged.get("system") if "record_lookup" in events else service
        owner = system_for(rid)
        if system != owner:
            stats["unattributed"] = stats.get("unattributed", 0) + 1
            continue
        id_fields = {k: v for k, v in merged.items() if k not in ("resource_id", "file", "object_key", "archive_key")}
        out.append(Observation(
            source_id=file_id,
            source_at=captured_at,
            t=when,
            system_id=system,
            resource_id=rid,
            kind="lookup" if "record_lookup" in events else "read",
            present=state.get("present"),
            exposed=state.get("exposed"),
            referenced=has_reference(merged),
            active=state.get("active"),
            record_type=merged.get("record_type"),
            attachment=state.get("attachment", False) or bool(merged.get("file", "").endswith(".pdf")),
            keys=frozenset(identifier_keys(id_fields)),
            where=f"{path.name} {group[0].trace or ''} {'+'.join(events)}".strip(),
        ))
    stats["observations"] = stats.get("observations", 0) + len(out)
    return out
