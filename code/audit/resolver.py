from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from .dataset import DATASET_DIR, Request, load_requests
from .identity import Identity, IdentityIndex
from .ingest import Corpus, load_corpus
from .intent import Intent, rule_intent
from .planner import Decision, decide, plan
from .policy import Policy
from .schema import Step, serialize_steps
from .state import state_at

STATUS_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
WINDOW_BEFORE = timedelta(minutes=80)
WINDOW_AFTER = timedelta(minutes=10)
POLICY_WINDOW = timedelta(minutes=31)


@dataclass
class CaseAudit:
    request: Request
    intent: Intent
    identity: Identity | None = None
    account: str | None = None
    account_reason: str = ""
    resources: dict = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    status: str = "NOT_APPLICABLE"
    steps: list[Step] = field(default_factory=list)


class Auditor:
    def __init__(self, corpus: Corpus | None = None, intent_fn=rule_intent):
        self.corpus = corpus or load_corpus()
        self.identities = IdentityIndex()
        self.policy = Policy()
        self.intent_fn = intent_fn
        self.by_resource = defaultdict(list)
        self.by_key = defaultdict(set)
        for o in self.corpus.observations:
            self.by_resource[o.resource_id].append(o)
            for k in o.keys:
                self.by_key[k].add(o.resource_id)
        self.claims_by_resource = defaultdict(list)
        for c in self.corpus.claims:
            self.claims_by_resource[c.resource_id].append(c)
        self.account_deletes = [c for c in self.corpus.claims
                                if c.event_type == "DELETE_RECORD" and c.target_system == "account_service"]
        self.accounts: dict[str, tuple[str, str]] = {}
        self.unlinked: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def owners(self, resource_id: str) -> set[str]:
        return {u for o in self.by_resource[resource_id] for u in self.identities.owners(o.keys)}

    def linked(self, request: Request, identity: Identity) -> dict[str, str]:
        """Resources an observation ties to the user between the request and the audit."""
        found = {}
        for key in identity.keys:
            for rid in self.by_key.get(key, ()):
                for o in self.by_resource[rid]:
                    if key in o.keys and request.requested_at <= o.t <= request.audit_at:
                        found.setdefault(rid, o.source_id)
        return found

    def assign_accounts(self, requests: list[Request]) -> None:
        """Each deletion case has one account; match the deletion worker's account delete to the request."""
        pending = {}
        taken = set()
        for r in requests:
            if not self.intent_fn(r.request_text).authorizes_deletion:
                continue
            ident = self.identities.resolve(r.email)
            if ident is None:
                continue
            accounts = sorted(rid for rid in self.linked(r, ident) if rid.startswith("account_"))
            if accounts:
                self.accounts[r.case_id] = (accounts[0], "identity link")
                taken.update(accounts)
                continue
            want = STATUS_RESULT.get(r.reported_status)
            cands = []
            for c in self.account_deletes:
                if not (r.reported_at - WINDOW_BEFORE <= c.t <= r.reported_at + WINDOW_AFTER and c.t <= r.audit_at):
                    continue
                if c.result != want:
                    continue
                if self.owners(c.resource_id) - {ident.user_id}:
                    continue
                cands.append(c.resource_id)
            pending[r.case_id] = (r, ident, sorted(set(cands)))

        while True:
            progress = False
            for case_id, (r, ident, cands) in list(pending.items()):
                free = [c for c in cands if c not in taken]
                if len(free) == 1:
                    self.accounts[case_id] = (free[0], "only free deletion-worker candidate")
                    taken.add(free[0])
                    del pending[case_id]
                    progress = True
            if not progress:
                break
        for case_id, (r, ident, cands) in sorted(pending.items(), key=lambda kv: (kv[1][0].requested_at, kv[0])):
            free = [c for c in cands if c not in taken]
            if free:
                self.accounts[case_id] = (free[0], f"tie among {len(free)} candidates, earliest request first")
                taken.add(free[0])
            else:
                number = int(ident.user_id.split("_")[1])
                self.accounts[case_id] = (f"account_{number:03d}", "convention: no candidate in the evidence")

    def assign_unlinked_ops(self, requests: list[Request]) -> None:
        """Anonymised analytics records carry no identifier; tie each to its request through the worker queue.

        Within one reporting batch (same reported_at), the deletion worker anonymises records in the same
        order as it deletes accounts. Assign only when the counts match, so nothing is guessed.
        """
        batches = defaultdict(list)
        for r in requests:
            if r.case_id in self.accounts:
                batches[r.reported_at].append(r)
        for reported_at, batch in batches.items():
            eligible = []
            for r in batch:
                ident = self.identities.resolve(r.email)
                if any(rid.startswith("analytics_") for rid in self.linked(r, ident)):
                    continue
                account = self.accounts[r.case_id][0]
                deletes = [c.t for c in self.claims_by_resource[account] if c.event_type == "DELETE_RECORD"]
                eligible.append((min(deletes) if deletes else r.reported_at, r))
            ops = sorted(
                (c for c in self.corpus.claims
                 if c.event_type == "ANONYMIZE_RECORD" and c.result == "SUCCESS"
                 and reported_at - POLICY_WINDOW <= c.t <= reported_at and not self.owners(c.resource_id)),
                key=lambda c: c.t,
            )
            if not ops or len(ops) != len(eligible):
                continue
            for (_, r), op in zip(sorted(eligible, key=lambda e: e[0]), ops):
                self.unlinked[r.case_id].append((op.resource_id, f"worker queue order, {op.activity_id}"))

    def audit(self, r: Request) -> CaseAudit:
        case = CaseAudit(r, self.intent_fn(r.request_text))
        if not case.intent.authorizes_deletion:
            return case
        case.identity = ident = self.identities.resolve(r.email)
        if ident is None:
            raise ValueError(f"{r.case_id}: request email matches no current or historical identity")

        resources = dict(self.linked(r, ident))
        account, reason = self.accounts.get(r.case_id, (None, ""))
        if account:
            case.account, case.account_reason = account, reason
            resources.setdefault(account, reason)
        for rid, why in self.unlinked.get(r.case_id, ()):
            resources.setdefault(rid, why)
        case.resources = resources

        for rid in sorted(resources):
            obs = self.by_resource[rid]
            system = obs[0].system_id if obs else f"{rid.rsplit('_', 1)[0]}_service"
            from .observations import system_for
            system = system_for(rid) or system
            claims = [c for c in self.claims_by_resource[rid] if c.t <= r.audit_at]
            category, why = self.policy.category(system, [o for o in obs if o.t <= r.audit_at])
            action, rule = self.policy.action(category, system, claims, explicit=why != "system default")
            st = state_at(rid, system, obs, self.corpus.snapshots, claims, ident.keys, r.reported_at, r.audit_at)
            d = decide(st, action)
            d.reason = f"{category} ({why}) -> {action} ({rule}); {', '.join(st.trail)}"
            case.decisions.append(d)
        case.status, case.steps = plan(case.decisions, r.audit_at)
        return case


def all_requests() -> list[Request]:
    return (load_requests(DATASET_DIR / "sample_deletion_requests.csv")
            + load_requests(DATASET_DIR / "deletion_requests.csv"))


def run_cases(requests: list[Request], auditor: Auditor | None = None) -> list[tuple[str, str, str]]:
    auditor = auditor or Auditor()
    known = {r.case_id for r in requests}
    everyone = requests + [r for r in all_requests() if r.case_id not in known]
    auditor.assign_accounts(everyone)
    auditor.assign_unlinked_ops(everyone)
    rows = []
    for r in requests:
        case = auditor.audit(r)
        rows.append((r.case_id, case.status, serialize_steps(case.steps) if case.steps else "[]"))
    return rows
