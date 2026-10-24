from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.dataset import DATASET_DIR, REPO_ROOT, evidence_times, load_requests  # noqa: E402
from audit.schema import OUTPUT_HEADER, case_number  # noqa: E402
from audit.resolver import build_auditor, run_cases  # noqa: E402
from audit.validate import validate_output  # noqa: E402


def run(requests, use_model: bool = True, offline: bool = False):
    auditor, client = build_auditor(use_model=use_model, offline=offline)
    return run_cases(requests, auditor), client


def write_output(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(OUTPUT_HEADER)
        writer.writerows(sorted(rows, key=lambda r: case_number(r[0])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghost Data deletion audit")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--offline", action="store_true", help="replay cached model answers; a cache miss is an error")
    parser.add_argument("--no-model", action="store_true", help="ablation: keyword intent, no document reading")
    args = parser.parse_args(argv)
    if args.no_model and args.out == REPO_ROOT / "output.csv":
        parser.error("--no-model is an ablation; give it its own --out so it cannot replace output.csv")

    requests = load_requests(args.requests)
    if args.only:
        requests = [r for r in requests if r.case_id in set(args.only)]

    rows, client = run(requests, use_model=not args.no_model, offline=args.offline)
    write_output(args.out, rows)
    if client is not None:
        for model, st in client.ledger.by_model.items():
            print(f"{model}: {st.calls} calls, {st.cache_hits} cache hits, "
                  f"{st.input_tokens} in / {st.output_tokens} out tokens, ${client.ledger.cost(model):.4f}")

    report = validate_output(args.out, requests, evidence_times())
    for w in report.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    print(f"wrote {len(rows)} rows to {args.out}; validator {'passed' if report.ok else 'FAILED'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
