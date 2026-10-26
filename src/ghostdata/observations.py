from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
USER_RE = re.compile(r"^user_\d+$")
PHONE_RE = re.compile(r"\+\d[\d ()-]{6,}\d")
RESOURCE_RE = re.compile(
    r"\b(account|search|analytics|support|export|backup|data_flow|audit_record|legal_hold|tombstone|"
    r"marketing|object|cache|email_delivery)_\d+\b"
)

PREFIX_SYSTEM = (
    ("audit_record_", "security_service"),
    ("data_flow_", "integration_service"),
    ("legal_hold_", "legal_service"),
    ("email_delivery_", "email_delivery_service"),
    ("account_", "account_service"),
    ("search_", "search_service"),
    ("analytics_", "analytics_platform"),
    ("support_", "support_platform"),
    ("export_", "export_service"),
    ("backup_", "backup_service"),
    ("tombstone_", "identity_service"),
    ("marketing_", "marketing_platform"),
    ("object_", "object_storage"),
    ("cache_", "cache_service"),
)

DIRECT_FIELDS = {
    "email", "phone", "email_hash", "full_name", "name", "display_name",
    "requester_name", "requester_email", "requester_phone", "owner_email", "owner_phone",
    "customer_email", "uploaded_by",
}
REFERENCE_FIELDS = {"user_id", "customer_reference", "subject_reference", "subject_ref", "subject_selector"}


def system_for(resource_id: str) -> str | None:
    for prefix, system in PREFIX_SYSTEM:
        if resource_id.startswith(prefix):
            return system
    return None


def phone_key(value: str) -> str:
    return "+" + re.sub(r"\D", "", value)


def identifier_keys(value) -> set[str]:
    """Normalised identifiers found anywhere inside a value."""
    keys: set[str] = set()
    if value is None:
        return keys
    if isinstance(value, dict):
        for v in value.values():
            keys |= identifier_keys(v)
        return keys
    if isinstance(value, (list, tuple)):
        for v in value:
            keys |= identifier_keys(v)
        return keys
    if not isinstance(value, str):
        return keys
    s = value.strip()
    if USER_RE.match(s):
        keys.add(s)
    elif HASH_RE.match(s):
        keys.add(s.lower())
    for m in EMAIL_RE.findall(s):
        keys.add(m.lower())
    for m in PHONE_RE.findall(s):
        keys.add(phone_key(m))
    return keys


def is_set(value) -> bool:
    return value not in (None, "", "null", "None", [], {})


def has_direct_identifier(record: dict) -> bool:
    for k, v in record.items():
        if isinstance(v, dict) and has_direct_identifier(v):
            return True
        if k in DIRECT_FIELDS and is_set(v) and v != "[REDACTED]":
            return True
        if k in ("message_text", "message_excerpt", "matched_value") and isinstance(v, str):
            if EMAIL_RE.search(v) or PHONE_RE.search(v):
                return True
    return False


def has_reference(record: dict) -> bool:
    for k, v in record.items():
        if isinstance(v, dict) and has_reference(v):
            return True
        if k in REFERENCE_FIELDS and is_set(v):
            return True
    return False


@dataclass(frozen=True)
class Observation:
    """One fact about one resource, read from one source at one time."""

    source_id: str
    source_at: datetime
    t: datetime
    system_id: str
    resource_id: str
    kind: str
    present: bool | None = None
    exposed: bool | None = None
    referenced: bool | None = None
    active: bool | None = None
    record_type: str | None = None
    collection: str | None = None
    attachment: bool = False
    keys: frozenset = field(default_factory=frozenset)
    where: str = ""


@dataclass(frozen=True)
class Snapshot:
    """A full capture of some systems: a resource it does not list was absent at time t."""

    source_id: str
    source_at: datetime
    t: datetime
    systems: frozenset | None
    resources: frozenset
    keys: frozenset
    where: str = ""

    def covers(self, system_id: str) -> bool:
        return self.systems is None or system_id in self.systems


@dataclass
class Evidence:
    observations: list[Observation] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)


DATA_SYSTEMS = {system for _, system in PREFIX_SYSTEM}

RESULT_STATE = {
    "FOUND": dict(present=True),
    "NOT_FOUND": dict(present=False),
    "IDENTIFIABLE": dict(present=True, exposed=True),
    "ANONYMIZED": dict(present=True, exposed=False),
    "REDACTED": dict(present=True, exposed=False),
    "ACTIVE": dict(present=True, active=True),
    "DISABLED": dict(present=True, active=False),
    "BLOCKED": dict(present=True, active=False),
}


def truthy(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None
