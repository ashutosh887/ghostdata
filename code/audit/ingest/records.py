from __future__ import annotations

from datetime import datetime

from ..observations import (RESULT_STATE, Observation, has_direct_identifier, has_reference, identifier_keys,
                            truthy)

NON_IDENTITY_FIELDS = ("resource_id", "file_name", "object_key", "archive_key", "archive_path", "updated_at",
                       "observed_at", "recorded_at", "created_at", "expires_at", "retention_until", "retained_until",
                       "integrity_seal")


def record_observation(source_id: str, source_at: datetime, t: datetime, system: str, rid: str, rec: dict,
                       collection: str | None, where: str, kind: str = "record") -> Observation:
    """A record read directly from a store: it exists, and its fields show what it still exposes."""
    referenced = has_reference(rec)
    exposed = has_direct_identifier(rec)
    if system == "analytics_platform":
        exposed = exposed or referenced
    active = None
    if system == "integration_service":
        active = truthy(rec.get("enabled"))
    elif system == "backup_service":
        active = truthy(rec.get("restore_allowed"))
    present = True
    if "status_code" in rec:
        present = str(rec["status_code"]) == "200"
    ids = {k: v for k, v in rec.items() if k not in NON_IDENTITY_FIELDS}
    return Observation(
        source_id=source_id,
        source_at=source_at,
        t=t,
        system_id=system,
        resource_id=rid,
        kind=kind,
        present=present,
        exposed=exposed if present else None,
        referenced=referenced,
        active=active,
        collection=collection,
        attachment=collection == "ticket_attachments",
        keys=frozenset(identifier_keys(ids)),
        where=where,
    )


def lookup_observation(source_id: str, source_at: datetime, t: datetime, system: str, rid: str, record_type: str,
                       result: str, subject: str | None, where: str) -> Observation:
    """A lookup line that states a result (FOUND, NOT_FOUND, ANONYMIZED...) for a record."""
    state = RESULT_STATE[result]
    return Observation(
        source_id=source_id,
        source_at=source_at,
        t=t,
        system_id=system,
        resource_id=rid,
        kind="lookup",
        present=state.get("present"),
        exposed=state.get("exposed"),
        active=state.get("active"),
        record_type=record_type,
        attachment=record_type == "SUPPORT_ATTACHMENT",
        keys=frozenset(identifier_keys(subject)),
        where=where,
    )
