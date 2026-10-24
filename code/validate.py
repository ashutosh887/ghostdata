from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.dataset import DATASET_DIR, REPO_ROOT, evidence_times, load_requests  # noqa: E402
from audit.validate import validate_output  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an output file against the submission contract")
    parser.add_argument("output", type=Path, nargs="?", default=REPO_ROOT / "output.csv")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    args = parser.parse_args()

    report = validate_output(args.output, load_requests(args.requests), evidence_times())
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    print(f"{len(report.errors)} errors, {len(report.warnings)} warnings")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
