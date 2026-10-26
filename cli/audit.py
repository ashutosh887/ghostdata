from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostdata.dataset import DATASET_DIR, REPO_ROOT, evidence_times, load_requests  # noqa: E402
from ghostdata.schema import OUTPUT_HEADER, case_number  # noqa: E402
from ghostdata.resolver import build_auditor, run_cases  # noqa: E402
from ghostdata.validate import validate_output  # noqa: E402
from ghostdata.agent.llm import ModelUnavailable  # noqa: E402
from ghostdata.ingest.documents import ToolMissing  # noqa: E402


def run(requests, use_model: bool = True, offline: bool = False, fresh: bool = False):
    auditor = build_auditor(use_model=use_model, offline=offline, fresh=fresh)
    return run_cases(requests, auditor), auditor


def write_output(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(OUTPUT_HEADER)
        writer.writerows(sorted(rows, key=lambda r: case_number(r[0])))


def degraded(requests, rows, auditor, client) -> None:
    """Warn for every row a model outage pushed onto a rules path, then one summary line with the caps."""
    texts = {r.request_text for r in requests if auditor.intent(r.request_text).source == "rules-fallback"}
    for r in requests:
        if r.request_text in texts:
            print(f"warning: {r.case_id}: model unavailable for intent; decided by the keyword rule", file=sys.stderr)
    unread = sorted({s for role, s, _ in client.fallbacks if role == "vision"})
    for file_id in unread:
        print(f"warning: {file_id}: model unavailable for the document; assumed to expose its record", file=sys.stderr)
    citing = sum(any(f'"{f}"' in steps for f in unread) for _, _, steps in rows)
    t = client.ledger.totals()
    print(f"degraded: {sum(r.request_text in texts for r in requests)} rows used the keyword rule for intent, "
          f"{len(unread)} documents unread and assumed exposed ({citing} rows cite them); "
          f"caps {client.caps.describe()}, live spend ${client.ledger.total_cost():.4f} in {t.calls} calls")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghost Data deletion audit")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--offline", action="store_true", help="replay cached model answers; a cache miss is an error")
    parser.add_argument("--no-model", action="store_true", help="ablation: keyword intent, no document reading")
    parser.add_argument("--fresh", action="store_true", help="ignore cached answers and call every model live")
    parser.add_argument("--usage-report", type=Path, help="write the token and cost report for this run")
    args = parser.parse_args(argv)
    if args.no_model and args.out == REPO_ROOT / "output.csv":
        parser.error("--no-model is an ablation; give it its own --out so it cannot replace output.csv")

    requests = load_requests(args.requests)
    if args.only:
        requests = [r for r in requests if r.case_id in set(args.only)]

    if args.fresh and args.offline:
        parser.error("--fresh calls the models live; it cannot be combined with --offline")
    if args.usage_report and not args.fresh:
        parser.error("--usage-report describes live calls; run it with --fresh")
    try:
        rows, auditor = run(requests, use_model=not args.no_model, offline=args.offline, fresh=args.fresh)
    except (ModelUnavailable, ToolMissing) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    write_output(args.out, rows)
    for r in requests:
        reason = auditor.intent(r.request_text).authorizes_deletion and auditor.unusable(r)
        if reason:
            print(f"warning: {r.case_id}: {reason}; written as NOT_APPLICABLE", file=sys.stderr)
    client = auditor.client
    if client is not None:
        investigations = auditor.investigations
        if investigations:
            accepted = sum(len(x.accepted) for x in investigations)
            rejected = sum(len(x.rejected) for x in investigations)
            unresolved = sum(x.outcome.startswith("declare_unresolvable") for x in investigations)
            print(f"investigator: {len(investigations)} flagged cases, {unresolved} declared unresolvable, "
                  f"{accepted} proposals accepted, {rejected} rejected")
        print(f"injection patterns flagged: {len(auditor.request_flags)} request texts, {len(auditor.document_flags)} documents "
              f"(each is fenced as data in its prompt)")
        if args.usage_report:
            when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            args.usage_report.write_text(client.ledger.report(len(requests), auditor.investigations, when), encoding="utf-8")
            print(f"wrote {args.usage_report}")
        for model, st in client.ledger.by_model.items():
            print(f"{model}: {st.calls} calls, {st.cache_hits} cache hits, "
                  f"{st.input_tokens} in / {st.output_tokens} out tokens, ${client.ledger.cost(model):.4f}")
        degraded(requests, rows, auditor, client)

    report = validate_output(args.out, requests, evidence_times())
    for w in report.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    print(f"wrote {len(rows)} rows to {args.out}; validator {'passed' if report.ok else 'FAILED'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
