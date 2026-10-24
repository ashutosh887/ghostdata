from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
EVAL = CODE_DIR / "evaluation"
sys.path.insert(0, str(EVAL))

from custom_cases.cases import CASES  # noqa: E402

OUT = EVAL / "evaluation_report.md"
SYSTEMS = [("agent", "Agent (model + code)"), ("rules", "Rules only (no model)"),
           ("trust_workflow", "Baseline: trust the workflow's claim"), ("always_incomplete", "Baseline: always INCOMPLETE")]


def score(system: str, split: str, offline: bool) -> dict:
    cmd = [sys.executable, str(EVAL / "main.py"), "--json", "--system", system, "--split", split]
    cmd += ["--offline"] if offline and system == "agent" else []
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def headline_table(rows: list[tuple[str, dict]]) -> list[str]:
    lines = ["| System | False COMPLETE | Steps on NOT_APPLICABLE | Status | Exact steps_json | Step P / R / F1 | F1 ignoring evidence_id | Order agrees | Sequence similarity |",
             "|---|---|---|---|---|---|---|---|---|"]
    for label, s in rows:
        p, r, f = s["step_prf"]
        lines.append(f"| {label} | {s['false_complete']} | {s['unauthorised_steps']} | {s['status_accuracy']} | {s['exact_match']} | "
                     f"{p:.3f} / {r:.3f} / {f:.3f} | {s['step_prf_no_evidence'][2]:.3f} | {s['sequence_order_ok']} | {s['sequence_similarity']} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Write evaluation_report.md from fresh scorer runs")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--holdout", action="store_true", help="score the frozen holdout; do this once, after the last change")
    args = parser.parse_args()

    dev = [(label, score(system, "dev", args.offline)) for system, label in SYSTEMS]
    agent = dev[0][1]
    custom = subprocess.run([sys.executable, str(EVAL / "custom.py"), *(["--offline"] if args.offline else [])],
                            capture_output=True, text=True, check=True).stdout
    custom_lines = [ln for ln in custom.splitlines() if ln.startswith(("PASS", "FAIL", "     "))]
    custom_total = re.search(r"(\d+/\d+) custom cases exact", custom)

    lines = [
        "# Evaluation report",
        "",
        "All numbers come from `python3 code/evaluation/report.py`, which reruns every scorer below. Labelled data is",
        "the 32 sample cases: 22 for development and 10 frozen as a holdout before any resolver code existed",
        "(`code/evaluation/splits.py`, seed 20261024, stratified by status).",
        "",
        "## Metrics",
        "",
        "- **False COMPLETE**: cases certified as deleted while data remains. This is the headline: it is the failure",
        "  the brief describes. **Steps on NOT_APPLICABLE**: deletion work proposed without authority.",
        "- **Status**: case-level `deletion_status` accuracy.",
        "- **Step P / R / F1**: steps matched as multisets on (phase, system_id, resource_id, operation, state, evidence_id).",
        "  The second F1 ignores evidence_id, which separates finding the right records from citing the right source.",
        "- **Field accuracy**: each step field compared position by position against the sample answer.",
        "- **Sequence**: whether the shared steps appear in the same order, and 1 minus the normalised edit distance",
        "  between the two step lists.",
        "",
        "## Development split (22 samples)",
        "",
        *headline_table(dev),
        "",
        "Field accuracy for the agent: " + ", ".join(f"{k} {v:.3f}" for k, v in agent["field_accuracy"].items()) + ".",
        "",
        "Per class for the agent: " + "; ".join(f"{k} precision {v['precision']}, recall {v['recall']}"
                                                  for k, v in agent["per_class"].items()) + ".",
        "",
        "The 8 dev cases that are not exact: case_18 and case_20 each need a security audit record whose id appears nowhere",
        "in the dataset; case_21, case_25, case_26 and case_27 each miss an anonymised analytics record that carries no",
        "identifier and shares its batch with other requests (F-004); case_28 and case_29 have swapped accounts because",
        "no evidence separates their two candidates (D-011).",
        "",
        "## Holdout (10 samples, scored once)",
        "",
    ]
    if args.holdout:
        hold = [(label, score(system, "holdout", args.offline)) for system, label in SYSTEMS]
        lines += headline_table(hold)
    else:
        lines.append("Not scored yet. It is scored once, after the last code change, with `report.py --holdout`.")
    lines += [
        "",
        "## Custom evaluation cases",
        "",
        f"Six hand-built cases run through the real pipeline on a copy of the dataset with the case's users, activity and",
        f"evidence added (`code/evaluation/custom.py`). Result: {custom_total.group(1)} exact.",
        "",
        "| Case | What it tests | Why it matters | Expected |",
        "|---|---|---|---|",
    ]
    for c in CASES:
        status, steps = c["expected"]
        lines.append(f"| {c['case_id']} | {c['title']} | {c['why']} | {status}, {len(steps)} step{'s' if len(steps) != 1 else ''} |")
    lines += ["", "Run output:", "", "```", *custom_lines, "```", ""]

    probes = subprocess.run([sys.executable, str(EVAL / "intent_probes.py"), *(["--offline"] if args.offline else [])],
                            capture_output=True, text=True, check=True).stdout.strip().splitlines()
    lines += [
        "## Intent probes outside the dataset",
        "",
        "Hand-written requests in five more languages and phrasings the dataset does not use: synonyms, corrections,",
        "hypotheticals, opt-outs and injected instructions (`code/evaluation/intent_probes.json`). The tuned set found",
        "the two misses fixed in F-005; the held-out set was written after that fix, run once, and never used to change it.",
        "",
        "```", *probes, "```", "",
    ]

    lines += ["## Ablations", ""]
    ablations = (EVAL / "ablations.md").read_text(encoding="utf-8").splitlines()
    lines += [ln for ln in ablations if ln.startswith("|")]
    lines += ["", "Each removed mechanism changes answers; the interpretation is in `code/docs/DECISIONS.md` (D-012).", ""]

    lines += ["## Failures found and improvements made", "",
              "Full entries, each with cause, fix and before-and-after numbers, are in `code/docs/FAILURES.md`.", ""]
    failures = (CODE_DIR / "docs" / "FAILURES.md").read_text(encoding="utf-8")
    for title in re.findall(r"^## (F-\d+\..+)$", failures, flags=re.M):
        lines.append(f"- {title}")
    lines += ["", "## Score history on the development split", ""]
    history = (EVAL / "history.md").read_text(encoding="utf-8").splitlines()
    lines += [ln for ln in history if ln.startswith("|")]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
