from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.dataset import DATASET_DIR, REPO_ROOT, evidence_times, load_requests  # noqa: E402
from audit.schema import OUTPUT_HEADER, case_number  # noqa: E402
from audit.validate import validate_output  # noqa: E402


def resolve(request):
    # Phase 1 placeholder: the resolver replaces this in phase 4.
    return "NOT_APPLICABLE", "[]"


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
    args = parser.parse_args(argv)

    requests = load_requests(args.requests)
    if args.only:
        requests = [r for r in requests if r.case_id in set(args.only)]

    rows = [(r.case_id, *resolve(r)) for r in requests]
    write_output(args.out, rows)

    report = validate_output(args.out, requests, evidence_times())
    for w in report.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    print(f"wrote {len(rows)} rows to {args.out}; validator {'passed' if report.ok else 'FAILED'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
