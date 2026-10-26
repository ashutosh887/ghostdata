from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation" / "ablations.md"

ARMS = [
    ("full agent", "", []),
    ("no model: keyword intent, no document reading", "", ["--no-model"]),
    ("no identity history: current email, phone and hash only", "no_history", []),
    ("no time cut: evidence after audit_at counts", "no_time_filter", []),
    ("no request-time bound on discovery", "no_lower_bound", []),
    ("replica tables ignored", "no_replica", []),
    ("document readings swapped between screenshots", "swap_documents", []),
]


def run(cmd: list[str], ablate: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GHOST_ABLATE": ablate}
    return subprocess.run([sys.executable, *cmd], env=env, capture_output=True, text=True)


def rows(path: Path) -> dict:
    return {r["case_id"]: (r["deletion_status"], r["steps_json"]) for r in csv.DictReader(open(path, encoding="utf-8"))}


def main() -> int:
    reference = rows(ROOT / "output.csv")
    table = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, ablate, flags in ARMS:
            dev = json.loads(run([str(ROOT / "evaluation" / "main.py"), "--json",
                                  "--system", "rules" if "--no-model" in flags else "agent"], ablate).stdout.strip().splitlines()[-1])
            custom = run([str(ROOT / "evaluation" / "custom.py"), *flags], ablate).stdout
            passed = re.search(r"(\d+)/(\d+) custom cases exact", custom)
            out = Path(tmp) / "out.csv"
            full = run([str(ROOT / "cli" / "audit.py"), "--out", str(out), *flags], ablate)
            test = rows(out)
            changed = sum(test[c] != reference[c] for c in reference)
            to_complete = sum(test[c][0] == "COMPLETE" and reference[c][0] == "INCOMPLETE" for c in reference)
            table.append((label, dev, passed.group(0).split(" ")[0] if passed else "error",
                          changed, to_complete, "passed" if "validator passed" in full.stdout else "FAILED"))
            print(label, table[-1][1]["exact_match"], table[-1][2:], flush=True)

    lines = [
        "# Ablations",
        "",
        "Each arm switches off one mechanism (`GHOST_ABLATE`) and reruns the dev samples, the 6 custom cases and all 518",
        "test cases. 'Changed' counts test rows that differ from the full agent's output; 'new COMPLETE' counts test cases",
        "the arm would certify that the full agent reports as INCOMPLETE.",
        "",
        "| Arm | Dev false COMPLETE | Dev status | Dev exact | Dev step F1 | Custom exact | Test rows changed | Test new COMPLETE | Validator |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label, dev, custom, changed, to_complete, valid in table:
        lines.append(f"| {label} | {dev['false_complete']} | {dev['status_accuracy']} | {dev['exact_match']} | "
                     f"{dev['step_prf'][2]:.3f} | {custom} | {changed} | {to_complete} | {valid} |")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
