from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .agent.documents import DocumentReader
from .agent.intent import ModelIntent
from .agent.investigator import Investigation, Investigator
from .agent.llm import ModelClient
from .config import ablated, load_env
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
    """Decides every case from observations. Models may only feed it readings; they never set a status or a step."""

    def __init__(self, corpus: Corpus | None = None, intent_fn=rule_intent, client: ModelClient | None = None,
                 contradicted: dict | None = None):
        self.corpus = corpus or load_corpus()
        if ablated("no_replica"):
            self.corpus.observations = [o for o in self.corpus.observations if "replica" not in o.where.split(" ")[-1]]
        self.identities = IdentityIndex()
        self.policy = Policy()
        self.intent_fn = intent_fn
        self.client = client
        self.contradicted = contradicted or {}
        self._intents: dict[str, Intent] = {}

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
        self.candidates: dict[str, list[str]] = {}
        self.unlinked: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.overrides: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        self.investigations: list[Investigation] = []

    def intent(self, text: str) -> Intent:
        if text not in self._intents:
            self._intents[text] = self.intent_fn(text)
        return self._intents[text]

    def owners(self, resource_id: str) -> set[str]:
        return {u for o in self.by_resource[resource_id] for u in self.identities.owners(o.keys)}

    def linked(self, request: Request, identity: Identity) -> dict[str, str]:
        """Resources an observation ties to the user between the request and the audit."""
        since = datetime.min.replace(tzinfo=request.audit_at.tzinfo) if ablated("no_lower_bound") else request.requested_at
        found = {}
        for key in identity.keys:
            for rid in self.by_key.get(key, ()):
                for o in self.by_resource[rid]:
                    if key in o.keys and since <= o.t <= request.audit_at:
                        found.setdefault(rid, o.source_id)
        return found

    def _delete_candidates(self, r: Request, ident: Identity) -> list[str]:
        """Account deletes by the worker in the processing window whose result matches the reported status."""
        want = STATUS_RESULT.get(r.reported_status)
        cands = {
            c.resource_id for c in self.account_deletes
            if r.reported_at - WINDOW_BEFORE <= c.t <= r.reported_at + WINDOW_AFTER and c.t <= r.audit_at
            and c.result == want and not self.owners(c.resource_id) - {ident.user_id}
        }
        return sorted(cands)

    def assign_accounts(self, requests: list[Request]) -> None:
        """Each deletion case has one account: an identity link if any, else the worker's matching delete."""
        pending: dict[str, tuple[Request, Identity]] = {}
        taken: set[str] = set()
        for r in requests:
            ident = self.identities.resolve(r.email)
            if ident is None or not self.intent(r.request_text).authorizes_deletion:
                continue
            accounts = sorted(rid for rid in self.linked(r, ident) if rid.startswith("account_"))
            if accounts:
                self.accounts[r.case_id] = (accounts[0], "identity link")
                taken.update(accounts)
            else:
                self.candidates[r.case_id] = self._delete_candidates(r, ident)
                pending[r.case_id] = (r, ident)

        progress = True
        while progress:
            progress = False
            for case_id in list(pending):
                free = [c for c in self.candidates[case_id] if c not in taken]
                if len(free) == 1:
                    self.accounts[case_id] = (free[0], "only free deletion-worker candidate")
                    taken.add(free[0])
                    del pending[case_id]
                    progress = True

        for case_id, (r, ident) in sorted(pending.items(), key=lambda kv: (kv[1][0].requested_at, kv[0])):
            free = [c for c in self.candidates[case_id] if c not in taken]
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
            eligible = [r for r in batch
                        if not any(rid.startswith("analytics_") for rid in self.linked(r, self.identities.resolve(r.email)))]
            ops = [c for c in self.corpus.claims
                   if c.event_type == "ANONYMIZE_RECORD" and c.result == "SUCCESS"
                   and reported_at - POLICY_WINDOW <= c.t <= reported_at and not self.owners(c.resource_id)]
            if len(ops) == 1 and len(eligible) == 1:
                self.unlinked[eligible[0].case_id].append(
                    (ops[0].resource_id, f"only unowned anonymisation in its batch, {ops[0].activity_id}"))

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

    def scope(self, r: Request, ident: Identity) -> tuple[dict[str, str], str | None, str]:
        """Every record in scope with the reason it was found, plus the account and why it was chosen."""
        resources = dict(self.linked(r, ident))
        account, reason = self.accounts.get(r.case_id, (None, ""))
        for kind, rid, why in self.overrides.get(r.case_id, ()):
            if kind == "account":
                account, reason = rid, why
            else:
                resources.setdefault(rid, why)
        if account:
            resources.setdefault(account, reason)
        for rid, why in self.unlinked.get(r.case_id, ()):
            resources.setdefault(rid, why)
        return resources, account, reason

    def audit(self, r: Request) -> CaseAudit:
        case = CaseAudit(r, self.intent(r.request_text))
        if not case.intent.authorizes_deletion:
            return case
        case.identity = ident = self.identities.resolve(r.email)
        if ident is None:
            raise ValueError(f"{r.case_id}: request email matches no current or historical identity")
        case.resources, case.account, case.account_reason = self.scope(r, ident)

        for rid in sorted(case.resources):
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

    def investigate(self, requests: list[Request], workers: int = 8) -> None:
        """Run the investigator on flagged cases and apply only the proposals code accepted."""
        if self.client is None:
            return
        investigator = Investigator(self, self.client)
        deletion = [r for r in requests if self.intent(r.request_text).authorizes_deletion]
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(investigator.run, deletion))
        self.investigations = [x for x in results if x.flags]
        for x in self.investigations:
            for name, rid, evidence, why in x.accepted:
                kind = "account" if name == "propose_account" else "resource"
                self.overrides[x.case_id].append((kind, rid, f"investigator: {evidence} ({why})"))


def all_requests() -> list[Request]:
    return (load_requests(DATASET_DIR / "sample_deletion_requests.csv")
            + load_requests(DATASET_DIR / "deletion_requests.csv"))


def build_auditor(use_model: bool = True, offline: bool = False) -> Auditor:
    """The full agent: the model reads intent and documents, code decides everything else."""
    corpus = load_corpus()
    if not use_model:
        return Auditor(corpus)
    load_env()
    client = ModelClient(offline=offline)
    reader = DocumentReader(client)
    reader.apply(corpus)
    return Auditor(corpus, intent_fn=ModelIntent(client), client=client, contradicted=reader.contradicted)


def run_cases(requests: list[Request], auditor: Auditor) -> list[tuple[str, str, str]]:
    known = {r.case_id for r in requests}
    everyone = requests + [r for r in all_requests() if r.case_id not in known]
    auditor.assign_accounts(everyone)
    auditor.assign_unlinked_ops(everyone)
    auditor.investigate(requests)
    rows = []
    for r in requests:
        case = auditor.audit(r)
        rows.append((r.case_id, case.status, serialize_steps(case.steps) if case.steps else "[]"))
    return rows
