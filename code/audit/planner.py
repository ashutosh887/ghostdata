from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .schema import Step, order_steps
from .state import Proof, ResourceState

PLAYBOOK = {
    "DELETE": ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    "REDACT": ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    "ANONYMIZE": ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    "BLOCK_RESTORE": ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
    "DISABLE_FLOW": ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    "RETAIN": (None, None, "VERIFY_RECORD_PRESENT"),
}


@dataclass
class Decision:
    resource_id: str
    system_id: str
    action: str
    violated: bool
    proof: list[Proof]
    reason: str

    @property
    def unverified(self) -> bool:
        """No source shows the state this record is in, so it cannot be certified either way."""
        return not self.proof


def cite(proofs: list[Proof], audit_at: datetime) -> str:
    """Prefer a source that existed by audit_at, then the newest observation."""
    if not proofs:
        return ""
    best = max(proofs, key=lambda p: (p.source_at <= audit_at, p.t, p.source_id))
    return best.source_id


def decide(st: ResourceState, action: str) -> Decision:
    if action == "DELETE":
        violated = bool(st.present)
        proofs = st.presence_proof
    elif action in ("REDACT", "ANONYMIZE"):
        violated = bool(st.present) and bool(st.exposed)
        proofs = st.exposure_proof if violated else (st.exposure_proof or st.presence_proof)
    elif action in ("BLOCK_RESTORE", "DISABLE_FLOW"):
        violated = bool(st.active)
        proofs = st.activity_proof
    else:
        violated = False
        proofs = [p for p in st.presence_proof] if st.present else []
    return Decision(st.resource_id, st.system_id, action, violated, proofs, "")


def plan(decisions: list[Decision], audit_at: datetime) -> tuple[str, list[Step]]:
    complete = not any(d.violated for d in decisions)
    steps = []
    for d in decisions:
        finding, fix, check = PLAYBOOK[d.action]
        evidence = cite(d.proof, audit_at)
        if d.violated:
            steps.append(Step(d.system_id, d.resource_id, finding, evidence))
            steps.append(Step(d.system_id, d.resource_id, fix))
        steps.append(Step(d.system_id, d.resource_id, check, evidence if complete else ""))
    return ("COMPLETE" if complete else "INCOMPLETE"), order_steps(steps)
