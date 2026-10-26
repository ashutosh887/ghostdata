from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation"))

from ghostdata.dataset import DATASET_DIR  # noqa: E402
from custom_cases.cases import CASES  # noqa: E402
from score import score_case  # noqa: E402

REQUEST_FIELDS = ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"]


def append_rows(src: Path, dst: Path, rows: list[tuple]) -> None:
    text = src.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    with open(dst, "w", newline="", encoding="utf-8") as f:
        f.write(text)
        csv.writer(f, lineterminator="\n").writerows(rows)


def build_overlay(root: Path, cases: list[dict]) -> Path:
    """A dataset folder holding the real files plus each case's users, activity, evidence and request."""
    data = root / "dataset"
    (data / "evidence").mkdir(parents=True)
    for sub in (DATASET_DIR / "evidence").iterdir():
        (data / "evidence" / sub.name).symlink_to(sub)
    (data / "evidence" / "custom").mkdir()
    for name in ("sample_deletion_requests.csv", "sample_output.csv", "deletion_rules.csv", "output.csv"):
        (data / name).symlink_to(DATASET_DIR / name)

    users, audits, activity, manifest, requests = [], [], [], [], []
    for c in cases:
        for uid, name, email, phone, updated in c["users"]:
            from custom_cases.cases import sha
            users.append((uid, name, email, phone, sha(email), updated))
        audits += c["audit_log"]
        activity += c["activity"]
        for file_id, rel, captured, content in c["files"]:
            path = data / "evidence" / "custom" / Path(rel).name
            path.write_text(content, encoding="utf-8")
            manifest.append((file_id, f"evidence/custom/{path.name}", "custom_evaluation_case", captured))
        requests.append((c["case_id"], *c["request"]))

    append_rows(DATASET_DIR / "user_identities.csv", data / "user_identities.csv", users)
    append_rows(DATASET_DIR / "user_audit_log.csv", data / "user_audit_log.csv", audits)
    append_rows(DATASET_DIR / "system_activity.csv", data / "system_activity.csv", activity)
    append_rows(DATASET_DIR / "evidence_files.csv", data / "evidence_files.csv", manifest)
    append_rows(DATASET_DIR / "deletion_requests.csv", data / "deletion_requests.csv", requests)
    with open(root / "custom_requests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(REQUEST_FIELDS)
        w.writerows(requests)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the hand-built evaluation cases through the real pipeline")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = build_overlay(root, CASES)
        out = root / "out.csv"
        cmd = [sys.executable, str(ROOT / "cli" / "audit.py"), "--requests", str(root / "custom_requests.csv"), "--out", str(out)]
        cmd += ["--offline"] if args.offline else []
        cmd += ["--no-model"] if args.no_model else []
        run = subprocess.run(cmd, env={**os.environ, "GHOST_DATASET": str(data)}, capture_output=True, text=True)
        print(run.stdout.strip())
        if run.returncode != 0 and not out.exists():
            print(run.stderr[-2000:])
            return 1
        pred = {r["case_id"]: r for r in csv.DictReader(open(out, encoding="utf-8"))}

    passed = 0
    for c in CASES:
        status, steps = c["expected"]
        gold = [dict(s, step_no=i) for i, s in enumerate(steps, start=1)]
        row = pred[c["case_id"]]
        res = score_case(c["case_id"], status, gold, row["deletion_status"], json.loads(row["steps_json"]))
        passed += res.exact
        print(f"{'PASS' if res.exact else 'FAIL'} {c['case_id']} {c['title']}: expected {status}, got {row['deletion_status']}")
        for k in res.missing:
            print(f"     missing {k}")
        for k in res.extra:
            print(f"     extra   {k}")
    print(f"{passed}/{len(CASES)} custom cases exact")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
