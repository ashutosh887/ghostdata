from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..config import INVESTIGATOR_MAX_ROUNDS, MODELS, PROMPT_DIR
from ..dataset import Request
from .guard import fence
from .llm import ModelClient

TOOLS = ["case_summary", "find_by_identifier", "observations", "claims", "candidate_accounts",
         "propose_account", "propose_resource", "declare_unresolvable", "finish"]
SCHEMA = {
    "title": "investigator_step",
    "type": "object",
    "properties": {
        "tool": {"type": "string", "enum": TOOLS},
        "value": {"type": "string"},
        "resource_id": {"type": "string"},
        "evidence_id": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["tool", "value", "resource_id", "evidence_id", "reason"],
    "additionalProperties": False,
}


@dataclass
class Investigation:
    case_id: str
    flags: list
    transcript: list = field(default_factory=list)
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    outcome: str = ""


class Investigator:
    """A bounded tool loop. The model chooses what to look at; code runs the tools and checks every proposal."""

    def __init__(self, auditor, client: ModelClient, model: str = MODELS["investigator"]):
        self.auditor = auditor
        self.client = client
        self.model = model
        self.system = (PROMPT_DIR / "investigator.md").read_text(encoding="utf-8")

    def flags(self, r: Request) -> list[str]:
        out = []
        reason = self.auditor.accounts.get(r.case_id, ("", ""))[1]
        if reason.startswith("tie"):
            out.append("account_tie")
        if reason.startswith("convention"):
            out.append("account_convention")
        case = self.auditor.audit(r)
        if any(d.unverified for d in case.decisions):
            out.append("unverified")
        ident = self.auditor.identities.resolve(r.email)
        if ident and any(keys & ident.keys for _, keys in self.auditor.contradicted.values()):
            out.append("contradicted_link")
        return out

    def tool(self, r: Request, call: dict, inv: Investigation) -> str:
        a = self.auditor
        ident = a.identities.resolve(r.email)
        name, rid = call["tool"], call["resource_id"].strip()
        if name == "case_summary":
            case = a.audit(r)
            return json.dumps({
                "case_id": r.case_id, "requested_at": r.requested_at.isoformat(), "reported_at": r.reported_at.isoformat(),
                "audit_at": r.audit_at.isoformat(), "reported_status": r.reported_status,
                "user_id": ident.user_id, "emails": list(ident.emails),
                "account": [case.account, case.account_reason],
                "records": [{"resource_id": d.resource_id, "action": d.action, "violated": d.violated,
                             "unverified": d.unverified} for d in case.decisions],
            })
        if name == "find_by_identifier":
            value = call["value"].strip().lower()
            hits = sorted(a.by_key.get(value, ()))
            return json.dumps({"resources": hits[:40]})
        if name == "observations":
            rows = [{"source": o.source_id, "t": o.t.isoformat(), "present": o.present, "exposed": o.exposed,
                     "active": o.active, "identifier_owners": sorted(a.identities.owners(o.keys)), "where": o.where[:90]}
                    for o in sorted(a.by_resource.get(rid, ()), key=lambda o: o.t) if o.t <= r.audit_at]
            return json.dumps({"resource_id": rid, "observations": rows[:30]}) if rows else f"error: no observation of {rid!r} before the audit"
        if name == "claims":
            rows = [{"activity": c.activity_id, "t": c.t.isoformat(), "event": c.event_type, "result": c.result}
                    for c in a.claims_by_resource.get(rid, ()) if c.t <= r.audit_at]
            return json.dumps({"resource_id": rid, "claims": rows[:30]})
        if name == "candidate_accounts":
            return json.dumps({"candidates": a.account_candidates(r)})
        if name in ("propose_account", "propose_resource"):
            ok, why = a.verify_link(r, rid, call["evidence_id"].strip())
            entry = (name, rid, call["evidence_id"], call["reason"])
            (inv.accepted if ok else inv.rejected).append(entry)
            return f"accepted: {why}" if ok else f"rejected: {why}"
        return "ok"

    def run(self, r: Request) -> Investigation:
        inv = Investigation(r.case_id, self.flags(r))
        if not inv.flags:
            return inv
        history = [f"case {r.case_id}; flags: {', '.join(inv.flags)}"]
        for _ in range(INVESTIGATOR_MAX_ROUNDS):
            call = self.client.json("investigator", self.model, self.system, "\n".join(history), SCHEMA, max_tokens=300)
            if call["tool"] in ("declare_unresolvable", "finish"):
                inv.outcome = f"{call['tool']}: {call['reason']}"
                break
            result = self.tool(r, call, inv)
            inv.transcript.append((call, result))
            history.append(f"called {call['tool']}({call['value'] or call['resource_id']}) ->\n{fence('tool_result', result[:2500])}")
        else:
            inv.outcome = "stopped after the round limit"
        return inv
