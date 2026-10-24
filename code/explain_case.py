from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.dataset import Request, parse_time  # noqa: E402
from audit.agent.llm import ModelUnavailable  # noqa: E402
from audit.ingest.documents import ToolMissing  # noqa: E402
from audit.resolver import Auditor, all_requests, build_auditor  # noqa: E402


def show(auditor: Auditor, r: Request) -> None:
    case = auditor.audit(r)
    print(f"{r.case_id}  requested {r.requested_at:%Y-%m-%d %H:%M}  reported {r.reported_status} "
          f"{r.reported_at:%Y-%m-%d %H:%M}  audit {r.audit_at:%Y-%m-%d %H:%M}")
    print(f"text: {r.request_text}")
    print(f"intent: {'deletion' if case.intent.authorizes_deletion else 'not deletion'} "
          f"({case.intent.source}: {case.intent.reason})")
    if not case.intent.authorizes_deletion:
        print("status: NOT_APPLICABLE []")
        return
    ident = case.identity
    print(f"identity: {ident.user_id} {ident.name} via {ident.matched_by}; emails {', '.join(ident.emails)}")
    print(f"account: {case.account} ({case.account_reason})")
    print("resources:")
    for d in case.decisions:
        print(f"  {d.resource_id:<20} {d.system_id:<20} {d.action:<13} "
              f"{'VIOLATED' if d.violated else 'ok':<8} found via {case.resources[d.resource_id]}")
        print(f"      {d.reason}")
        for o in sorted(auditor.by_resource[d.resource_id], key=lambda o: o.t):
            late = " AFTER AUDIT" if o.t > r.audit_at else ""
            print(f"      {o.t:%m-%d %H:%M} {o.source_id:<13} present={o.present} exposed={o.exposed} "
                  f"active={o.active} {o.where[:60]}{late}")
        for c in auditor.claims_by_resource[d.resource_id]:
            late = " AFTER AUDIT" if c.t > r.audit_at else ""
            print(f"      {c.t:%m-%d %H:%M} {c.activity_id:<13} claim {c.event_type} {c.result}{late}")
    if case.note:
        print(f"note: {case.note}")
    print(f"status: {case.status}")
    for no, s in enumerate(case.steps, start=1):
        print(f"  {no:>2} {s.phase:<12} {s.operation:<26} {s.system_id:<20} {s.resource_id:<18} {s.evidence_id}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Trace how one case is decided")
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--email")
    parser.add_argument("--requested-at")
    parser.add_argument("--reported-status", default="COMPLETE")
    parser.add_argument("--reported-at")
    parser.add_argument("--audit-at")
    parser.add_argument("--text", default="Please delete my account.")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    requests = all_requests()
    auditor = build_auditor(use_model=not args.no_model, offline=args.offline)
    if args.email:
        r = Request("case_custom", args.email, parse_time(args.requested_at), args.reported_status,
                    parse_time(args.reported_at), parse_time(args.audit_at), args.text)
        if not r.requested_at <= r.audit_at:
            parser.error("--audit-at must not be before --requested-at")
        if auditor.identities.resolve(r.email) is None:
            parser.error(f"{args.email} matches no current or historical identity; nothing to audit")
        requests.append(r)
    else:
        r = next((x for x in requests if x.case_id == args.case_id), None)
        if r is None:
            parser.error(f"unknown case {args.case_id}")
    auditor.assign_accounts(requests)
    auditor.assign_unlinked_ops(requests)
    auditor.investigate([r])
    show(auditor, r)
    return 0


def main() -> int:
    try:
        return run()
    except ToolMissing as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ModelUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        print("A new request text has no recorded answer: run without --offline (needs the key), or use --no-model.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
