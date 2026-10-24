from __future__ import annotations

from pathlib import Path

from .dataset import DATASET_DIR, read_csv
from .ingest.activity import Claim
from .observations import Observation

DEFAULT_CATEGORY = {
    "account_service": "USER_PROFILE",
    "search_service": "SEARCH_INDEX_ENTRY",
    "analytics_platform": "ANALYTICS_PROFILE",
    "support_platform": "SUPPORT_MESSAGE",
    "export_service": "USER_EXPORT",
    "backup_service": "BACKUP_ARCHIVE",
    "integration_service": "DATA_FLOW",
    "security_service": "SECURITY_AUDIT_LOG",
    "legal_service": "LEGAL_HOLD_RECORD",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "marketing_platform": "MARKETING_PROFILE",
    "object_storage": "SUPPORT_ATTACHMENT",
    "cache_service": "CACHE_ENTRY",
    "email_delivery_service": "EMAIL_DELIVERY_LOG",
}

WORKER_ACTION = {"DELETE_RECORD": "DELETE", "REDACT_RECORD": "REDACT", "ANONYMIZE_RECORD": "ANONYMIZE"}


class Policy:
    def __init__(self, dataset_dir: Path = DATASET_DIR):
        self.rules = {r["data_category"]: r for r in read_csv(dataset_dir / "deletion_rules.csv")}

    def category(self, system_id: str, observations: list[Observation]) -> tuple[str, str]:
        """Data category of a record and the reason it was chosen."""
        typed = [o for o in observations if o.record_type]
        if typed:
            latest = max(typed, key=lambda o: o.t)
            return latest.record_type, f"record_type in {latest.source_id}"
        if system_id == "support_platform":
            hint = next((o for o in observations if o.attachment), None)
            if hint:
                return "SUPPORT_ATTACHMENT", f"attachment signal in {hint.source_id}"
        return DEFAULT_CATEGORY[system_id], "system default"

    def action(self, category: str, system_id: str, claims: list[Claim], explicit: bool) -> tuple[str, str]:
        """Required treatment: DELETE, REDACT, ANONYMIZE, RETAIN, BLOCK_RESTORE or DISABLE_FLOW."""
        if category == "DATA_FLOW":
            return "DISABLE_FLOW", "an active flow can recreate data"
        if category == "BACKUP_ARCHIVE":
            return "BLOCK_RESTORE", self.rules[category]["rule_id"]
        worker = [c for c in claims if c.event_type in WORKER_ACTION and c.target_system == system_id]
        rule = self.rules.get(category)
        if rule is None:
            raise KeyError(f"no deletion rule for category {category}")
        if worker and not explicit and rule["required_action"] not in ("RETAIN",):
            latest = max(worker, key=lambda c: c.t)
            return WORKER_ACTION[latest.event_type], f"deletion worker {latest.activity_id}"
        return rule["required_action"], rule["rule_id"]
