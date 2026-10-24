from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from .dataset import DATASET_DIR, Request, load_requests
from .identity import Identity, IdentityIndex
from .ingest import Corpus, load_corpus
from .intent import Intent, rule_intent
from .observations import system_for
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
        self.candidates: dict[str, list[str]] = {}
        self.contradicted: dict[str, tuple] = {}
        self.overrides: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

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
            self.candidates[r.case_id] = sorted(set(cands))

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
        """Anonymised analytics records carry no identifier; tie one to its request only when nothing else could own it.

        In one reporting batch (same reported_at), an unowned anonymisation by the deletion worker in the 31 minutes
        before the report belongs to the batch. With one eligible case and one such operation, the match is forced.
        With more, the worker's queue order would have to decide, and on accounts whose owner is known that order
        holds in only 10 of 23 pairs, so those batches stay unassigned.
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
            if len(ops) != 1 or len(eligible) != 1:
                continue
            self.unlinked[eligible[0][1].case_id].append((ops[0].resource_id, f"only unowned anonymisation in its batch, {ops[0].activity_id}"))

    def account_candidates(self, r: Request) -> list[dict]:
        out = []
        for rid in self.candidates.get(r.case_id, []):
            deletes = [c for c in self.claims_by_resource[rid] if c.event_type == "DELETE_RECORD"]
            out.append({"resource_id": rid, "deletes": [(c.activity_id, c.t.isoformat(), c.result) for c in deletes],
                        "owners_in_evidence": sorted(self.owners(rid)),
                        "assigned_to": [cid for cid, (acc, _) in self.accounts.items() if acc == rid]})
        return out

    def verify_link(self, r: Request, resource_id: str, evidence_id: str) -> tuple[bool, str]:
        """A proposal stands only under the discovery rule: the cited source shows one of the subject's
        identifiers on that record, at a time between the request and the audit."""
        ident = self.identities.resolve(r.email)
        if resource_id in self.linked(r, ident) or resource_id == self.accounts.get(r.case_id, ("",))[0]:
            return False, f"{resource_id} is already in scope"
        cited = [o for o in self.by_resource.get(resource_id, ()) if o.source_id == evidence_id]
        if not cited:
            return False, f"{evidence_id} has no observation of {resource_id}"
        for o in cited:
            shared = o.keys & ident.keys
            if shared and r.requested_at <= o.t <= r.audit_at:
                return True, f"{evidence_id} shows {sorted(shared)[0]} on {resource_id} at {o.t:%Y-%m-%d %H:%M}"
        if any(o.keys & ident.keys for o in cited):
            return False, f"{evidence_id} ties {resource_id} to {ident.user_id} only outside the request-to-audit window"
        return False, f"{evidence_id} shows none of {ident.user_id}'s identifiers on {resource_id}"

    def audit(self, r: Request) -> CaseAudit:
        case = CaseAudit(r, self.intent_fn(r.request_text))
        if not case.intent.authorizes_deletion:
            return case
        case.identity = ident = self.identities.resolve(r.email)
        if ident is None:
            raise ValueError(f"{r.case_id}: request email matches no current or historical identity")

        resources = dict(self.linked(r, ident))
        account, reason = self.accounts.get(r.case_id, (None, ""))
        for kind, rid, why in self.overrides.get(r.case_id, ()):
            if kind == "account":
                account, reason = rid, why
            else:
                resources.setdefault(rid, why)
        if account:
            case.account, case.account_reason = account, reason
            resources.setdefault(account, reason)
        for rid, why in self.unlinked.get(r.case_id, ()):
            resources.setdefault(rid, why)
        case.resources = resources

        for rid in sorted(resources):
            obs = self.by_resource[rid]
            system = system_for(rid)
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


def build_auditor(use_model: bool = True, offline: bool = False):
    """The full agent: the model reads intent and documents, code decides everything else."""
    corpus = load_corpus()
    if not use_model:
        return Auditor(corpus), None
    from .agent.documents import DocumentReader
    from .agent.intent import ModelIntent
    from .agent.llm import ModelClient
    from .config import load_env
    load_env()
    client = ModelClient(offline=offline)
    reader = DocumentReader(client)
    reader.apply(corpus)
    auditor = Auditor(corpus, intent_fn=ModelIntent(client))
    auditor.contradicted = reader.contradicted
    auditor.client = client
    return auditor, client


def run_cases(requests: list[Request], auditor: Auditor | None = None) -> list[tuple[str, str, str]]:
    auditor = auditor or Auditor()
    known = {r.case_id for r in requests}
    everyone = requests + [r for r in all_requests() if r.case_id not in known]
    auditor.assign_accounts(everyone)
    auditor.assign_unlinked_ops(everyone)
    if getattr(auditor, "client", None) is not None:
        investigate(auditor, requests)
    rows = []
    for r in requests:
        case = auditor.audit(r)
        rows.append((r.case_id, case.status, serialize_steps(case.steps) if case.steps else "[]"))
    return rows


def investigate(auditor: Auditor, requests: list[Request], workers: int = 8) -> None:
    """Run the investigator on flagged cases and apply only the proposals code accepted."""
    from concurrent.futures import ThreadPoolExecutor

    from .agent.investigator import Investigator

    inv = Investigator(auditor, auditor.client)
    deletion = [r for r in requests if auditor.intent_fn(r.request_text).authorizes_deletion]
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(inv.run, deletion))
    auditor.investigations = [x for x in results if x.flags]
    auditor.client.investigations = auditor.investigations
    for x in auditor.investigations:
        for name, rid, evidence, why in x.accepted:
            kind = "account" if name == "propose_account" else "resource"
            auditor.overrides[x.case_id].append((kind, rid, f"investigator: {evidence} ({why})"))
