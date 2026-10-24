from __future__ import annotations

import filecmp
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent
PY = sys.executable


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *args], capture_output=True, text=True, cwd=REPO_ROOT)


def unit_tests() -> tuple[bool, str]:
    r = subprocess.run([PY, "-m", "unittest", "discover", "-s", str(CODE_DIR / "tests")],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    return r.returncode == 0, r.stderr.strip().splitlines()[-3] if r.stderr.strip() else "no output"


def replay() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "output.csv"
        r = run(str(CODE_DIR / "main.py"), "--offline", "--out", str(out))
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines() or ["main.py failed"])[-1]
        same = filecmp.cmp(out, REPO_ROOT / "output.csv", shallow=False)
        return same, "offline replay matches output.csv byte for byte" if same else "offline replay differs from output.csv"


def validator() -> tuple[bool, str]:
    r = run(str(CODE_DIR / "validate.py"), str(REPO_ROOT / "output.csv"))
    return r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()


def dev_score() -> tuple[bool, str]:
    r = run(str(CODE_DIR / "evaluation" / "main.py"), "--offline", "--json")
    if r.returncode != 0:
        return False, "scorer failed"
    s = json.loads(r.stdout.strip().splitlines()[-1])
    ok = s["false_complete"] == 0 and s["status_accuracy"].startswith("22/22")
    return ok, f"false COMPLETE {s['false_complete']}, status {s['status_accuracy']}, exact {s['exact_match']}, step F1 {s['step_prf'][2]:.3f}"


def custom_cases() -> tuple[bool, str]:
    r = run(str(CODE_DIR / "evaluation" / "custom.py"), "--offline")
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "custom.py failed"
    return r.returncode == 0 and last.startswith("6/6"), last


def intent_probes() -> tuple[bool, str]:
    r = run(str(CODE_DIR / "evaluation" / "intent_probes.py"), "--offline")
    lines = r.stdout.strip().splitlines()
    scores = [re.search(r"model (\d+)/(\d+)", ln) for ln in lines]
    ok = r.returncode == 0 and bool(scores) and all(m and m.group(1) == m.group(2) for m in scores)
    return ok, "; ".join(lines) if lines else "intent_probes.py failed"


CHECKS = [
    ("unit tests", unit_tests),
    ("offline replay", replay),
    ("contract validator", validator),
    ("dev score", dev_score),
    ("custom cases", custom_cases),
    ("intent probes", intent_probes),
]


def main() -> int:
    """Every release gate in one command; any failure exits non-zero."""
    failed = 0
    for name, check in CHECKS:
        ok, detail = check()
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:<20} {detail}")
    print("all checks passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
