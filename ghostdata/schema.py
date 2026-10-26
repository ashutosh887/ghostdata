from __future__ import annotations

import json
from dataclasses import dataclass

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")

OPERATIONS = (
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
)

OP_PHASE = {op: phase for phase, op, _ in OPERATIONS}
OP_STATE = {op: state for _, op, state in OPERATIONS}
OP_RANK = {op: i for i, (_, op, _) in enumerate(OPERATIONS)}
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}

STEP_FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
OUTPUT_HEADER = ("case_id", "deletion_status", "steps_json")


@dataclass(frozen=True)
class Step:
    system_id: str
    resource_id: str
    operation: str
    evidence_id: str = ""

    @property
    def phase(self) -> str:
        return OP_PHASE[self.operation]

    @property
    def state(self) -> str:
        return OP_STATE[self.operation]


def sort_key(phase: str, operation: str, system_id: str, resource_id: str) -> tuple:
    return (PHASE_RANK[phase], OP_RANK[operation], system_id, resource_id)


def order_steps(steps: list[Step]) -> list[Step]:
    return sorted(steps, key=lambda s: sort_key(s.phase, s.operation, s.system_id, s.resource_id))


def serialize_steps(steps: list[Step]) -> str:
    rows = []
    for no, s in enumerate(order_steps(steps), start=1):
        rows.append({
            "step_no": no,
            "phase": s.phase,
            "system_id": s.system_id,
            "resource_id": s.resource_id,
            "operation": s.operation,
            "state": s.state,
            "evidence_id": s.evidence_id,
        })
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)


def case_number(case_id: str) -> int:
    return int(case_id.rsplit("_", 1)[1])
