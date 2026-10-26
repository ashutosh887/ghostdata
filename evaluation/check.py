from __future__ import annotations

import filecmp
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
BASELINE = ROOT / "evaluation" / "baseline.json"
TOLERANCE = 1e-9


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *args], capture_output=True, text=True, cwd=ROOT)


def unit_tests() -> tuple[bool, str]:
    r = subprocess.run([PY, "-m", "unittest", "discover", "-s", str(ROOT / "tests")],
                       capture_output=True, text=True, cwd=ROOT)
    lines = r.stderr.strip().splitlines()
    ran = next((ln for ln in lines if ln.startswith("Ran ")), "no tests ran")
    return r.returncode == 0, f"{ran}, {lines[-1] if lines else 'no output'}"


def replay() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "output.csv"
        r = run(str(ROOT / "cli" / "audit.py"), "--offline", "--out", str(out))
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines() or ["main.py failed"])[-1]
        same = filecmp.cmp(out, ROOT / "output.csv", shallow=False)
        return same, "offline replay matches output.csv byte for byte" if same else "offline replay differs from output.csv"


def validator() -> tuple[bool, str]:
    r = run(str(ROOT / "cli" / "validate.py"), str(ROOT / "output.csv"))
    return r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()


def ratio(text: str) -> float:
    right, total = text.split()[0].split("/")
    return int(right) / int(total) if int(total) else 1.0


def metrics(summary: dict) -> dict:
    """The numbers the gate pins: each one higher is better, except false_complete."""
    return {
        "false_complete": summary["false_complete"],
        "status_accuracy": ratio(summary["status_accuracy"]),
        "exact_match": ratio(summary["exact_match"]),
        "step_f1": summary["step_prf"][2],
        "sequence_order_ok": ratio(summary["sequence_order_ok"]),
        "sequence_similarity": summary["sequence_similarity"],
        "field_accuracy": dict(summary["field_accuracy"]),
    }


def _flat(m: dict) -> dict:
    return {**{k: v for k, v in m.items() if k not in ("false_complete", "field_accuracy")},
            **{f"field {k}": v for k, v in m.get("field_accuracy", {}).items()}}


def regressions(current: dict, baseline: dict) -> list[str]:
    """Every pinned number that got worse. A metric missing from the current run counts as a drop."""
    drops = [f"false COMPLETE {current.get('false_complete', 'missing')}"] if current.get("false_complete", 1) else []
    now = _flat(current)
    for name, pinned in sorted(_flat(baseline).items()):
        if name not in now or now[name] < pinned - TOLERANCE:
            drops.append(f"{name} {now.get(name, 'missing')} < pinned {pinned:.4f}")
    return drops


def dev_metrics() -> dict | None:
    r = run(str(ROOT / "evaluation" / "main.py"), "--offline", "--json")
    return metrics(json.loads(r.stdout.strip().splitlines()[-1])) if r.returncode == 0 else None


def dev_score() -> tuple[bool, str]:
    m = dev_metrics()
    if m is None:
        return False, "scorer failed"
    drops = regressions(m, json.loads(BASELINE.read_text(encoding="utf-8")))
    head = (f"false COMPLETE {m['false_complete']}, status {m['status_accuracy']:.3f}, exact {m['exact_match']:.3f}, "
            f"step F1 {m['step_f1']:.3f}")
    return not drops, f"{head}; no drop against baseline.json" if not drops else f"{head}; DROP: {'; '.join(drops)}"


def custom_cases() -> tuple[bool, str]:
    r = run(str(ROOT / "evaluation" / "custom.py"), "--offline")
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "custom.py failed"
    m = re.match(r"(\d+)/(\d+) custom cases exact", last)
    return r.returncode == 0 and bool(m) and m.group(1) == m.group(2), last


def intent_probes() -> tuple[bool, str]:
    r = run(str(ROOT / "evaluation" / "intent_probes.py"), "--offline")
    lines = r.stdout.strip().splitlines()
    scores = [re.search(r"model (\d+)/(\d+)", ln) for ln in lines]
    ok = r.returncode == 0 and bool(scores) and all(m and m.group(1) == m.group(2) for m in scores)
    return ok, "; ".join(lines) if lines else "intent_probes.py failed"


def report_current() -> tuple[bool, str]:
    committed = ROOT / "evaluation" / "evaluation_report.md"
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "report.md"
        text = committed.read_text(encoding="utf-8")
        holdout = [] if "Not printed here yet" in text else ["--holdout"]
        r = run(str(ROOT / "evaluation" / "report.py"), "--offline", *holdout, "--out", str(fresh))
        if r.returncode != 0:
            return False, "report.py failed"
        same = fresh.read_text(encoding="utf-8") == text
        return same, "evaluation_report.md matches a fresh run of every scorer" if same else \
            "evaluation_report.md is stale; rerun report.py --offline"


CHECKS = [
    ("unit tests", unit_tests),
    ("offline replay", replay),
    ("contract validator", validator),
    ("dev score", dev_score),
    ("custom cases", custom_cases),
    ("intent probes", intent_probes),
    ("evaluation report", report_current),
]


def pin() -> int:
    m = dev_metrics()
    if m is None or m["false_complete"]:
        print("refusing to pin: scorer failed or false COMPLETE is not 0", file=sys.stderr)
        return 1
    BASELINE.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pinned {BASELINE.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Every release gate in one command; any failure exits non-zero. --pin records the current dev score
    as the baseline the gate compares against; run it only after an improvement."""
    if (argv if argv is not None else sys.argv[1:]) == ["--pin"]:
        return pin()
    failed = 0
    for name, check in CHECKS:
        ok, detail = check()
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:<20} {detail}")
    print("all checks passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
