from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
os.environ.setdefault("GHOST_DATASET", str(DEMO / "dataset"))
os.environ.setdefault("GHOSTDATA_S3_PREFIX", "demo/")
sys.path.insert(0, str(ROOT))

from ghostdata.config import load_env  # noqa: E402
from ghostdata.dataset import DATASET_DIR, load_requests  # noqa: E402
from ghostdata.resolver import build_auditor, run_cases  # noqa: E402


def audit(requests, offline: bool, tool: bool, use_model: bool):
    os.environ["GHOST_ABLATE"] = "" if tool else "no_s3_tool"
    auditor = build_auditor(use_model=use_model, offline=offline)
    rows = {case_id: status for case_id, status, _ in run_cases(requests, auditor)}
    return rows, auditor


def score(scenarios: dict, off: dict, on: dict, auditor, after_fix: bool = False) -> dict:
    planted = [(cid, p) for cid, s in scenarios.items() for p in s.get("planted", [])]
    if after_fix:
        planted = [(cid, dict(p, expected="none") if p["expected"] == "ghost" else p) for cid, p in planted]
    deleted, kept, chained, model_found = set(), set(), set(), set()
    rounds = []
    for cid, hunt in auditor.hunts.items():
        rounds.append(sum(1 for name, _ in hunt.calls))
        for c in hunt.ghosts:
            (kept if c.legal_hold else deleted).add((cid, c.key, c.version_id))
            if set(c.matched) <= set(hunt.derived):
                chained.add((cid, c.key, c.version_id))
            if (c.key, c.version_id) in hunt.by_model:
                model_found.add((cid, c.key, c.version_id))

    def hit(found, cid, p):
        return any(f[0] == cid and f[1] == p["key"] and (not p.get("version_id") or f[2] == p["version_id"]) for f in found)

    ghosts = [(cid, p) for cid, p in planted if p["expected"] == "ghost"]
    holds = [(cid, p) for cid, p in planted if p["expected"] == "retained"]
    decoys = [(cid, p) for cid, p in planted if p["expected"] == "none"]
    truth = {cid: "COMPLETE" if after_fix and s["expected_after"] == "INCOMPLETE" else s["expected_after"]
             for cid, s in scenarios.items()}
    attacks = [cid for cid, s in scenarios.items() if s.get("attack")]
    controls = [cid for cid, t in truth.items() if t == "COMPLETE"]
    return {
        "cases": len(truth),
        "false_complete_off": sum(off.get(c) == "COMPLETE" and t == "INCOMPLETE" for c, t in truth.items()),
        "false_complete_on": sum(on.get(c) == "COMPLETE" and t == "INCOMPLETE" for c, t in truth.items()),
        "status_correct_off": sum(off.get(c) == t for c, t in truth.items()),
        "status_correct_on": sum(on.get(c) == t for c, t in truth.items()),
        "statuses_changed": sum(off.get(c) != on.get(c) for c in truth),
        "ghosts_planted": len(ghosts),
        "ghosts_found": sum(hit(deleted, cid, p) for cid, p in ghosts),
        "ghosts_found_by_model": sum(hit(model_found, cid, p) for cid, p in ghosts),
        "ghosts_found_only_by_chaining": sum(hit(chained, cid, p) for cid, p in ghosts),
        "false_findings": sum(hit(deleted | kept, cid, p) for cid, p in decoys)
        + len({(c, k) for c, k, _ in deleted} - {(cid, p["key"]) for cid, p in ghosts}),
        "holds_planted": len(holds),
        "holds_kept": sum(hit(kept, cid, p) and not hit(deleted, cid, p) for cid, p in holds),
        "controls": len(controls),
        "controls_still_complete": sum(on.get(c) == "COMPLETE" for c in controls),
        "attacks": len(attacks),
        "attacks_caught": sum(on.get(c) == truth[c] for c in attacks),
        "tool_calls_per_case": round(sum(rounds) / len(rounds), 2) if rounds else 0,
        "calls_refused_by_code": sum(len(h.refused) for h in auditor.hunts.values()),
        "hunts_finished_by_model": sum(h.outcome.startswith("finish") for h in auditor.hunts.values()),
        "hunts_degraded_to_code_sweep": sum("code sweep" in h.outcome for h in auditor.hunts.values()),
        "sweep_searches_after_the_model": sum(len(h.sweeps) for h in auditor.hunts.values()),
    }


def report(requests, scenarios, off, on, auditor, metrics, run: str) -> str:
    lines = [f"# Ghost Data demo: run `{run}`", "",
             "| case | scenario | tool off | tool on | S3 versions found |", "|---|---|---|---|---|"]
    for r in requests:
        hunt = auditor.hunts.get(r.case_id)
        found = "; ".join(f"`{c.key}` v`{c.version_id[:8]}`" + (" (legal hold, kept)" if c.legal_hold else "")
                          for c in hunt.ghosts) if hunt else ""
        name = scenarios.get(r.case_id, {}).get("scenario", "")
        lines.append(f"| {r.case_id} | {name} | {off[r.case_id]} | {on[r.case_id]} | {found} |")
    lines += ["", "| measure | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in metrics.items()]
    commands = [c.delete_command for h in auditor.hunts.values() for c in h.ghosts if not c.legal_hold]
    if commands:
        lines += ["", "Proposed, never run by the agent:", "", "```bash"] + sorted(set(commands)) + ["```"]
    return "\n".join(lines) + "\n"


def audit_time(requests, saved: Path, recorded: bool):
    """A live run audits now once the demo's fixed audit time has passed, so freshly seeded versions count;
    a recorded run replays the time its recording used."""
    if recorded:
        at = json.loads(saved.read_text(encoding="utf-8")).get("audit_at") if saved.exists() else None
        return datetime.fromisoformat(at) if at else None
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return now if all(r.audit_at < now for r in requests) else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit the demo cases with the S3 tool off, then on, and score both")
    parser.add_argument("--recorded", action="store_true", help="replay the recorded model and S3 answers; no credentials needed")
    parser.add_argument("--run", default="find", help="label for the S3 recording, e.g. find, then prove after the fixes")
    parser.add_argument("--no-model", action="store_true", help="ablation: keyword intent, and code sweeps S3 without the model")
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--after-fix", action="store_true",
                        help="score against the state after the proposed deletes ran: every deletion case should prove COMPLETE")
    args = parser.parse_args(argv)
    load_env()
    os.environ["GHOSTDATA_RUN"] = args.run
    scenarios = json.loads((DEMO / "scenarios.json").read_text(encoding="utf-8"))
    os.environ.setdefault("GHOSTDATA_S3_BUCKET", scenarios["bucket"])
    cases = scenarios["cases"]
    requests = load_requests(DATASET_DIR / "deletion_requests.csv")
    if args.only:
        requests = [r for r in requests if r.case_id in set(args.only)]
        cases = {c: s for c, s in cases.items() if c in set(args.only)}

    suffix = "-no-model" if args.no_model else ""
    saved = DEMO / "results" / f"{args.run}{suffix}.json"
    at = audit_time(requests, saved, args.recorded)
    if at:
        requests = [replace(r, audit_at=at) for r in requests]
    off, _ = audit(requests, args.recorded, tool=False, use_model=not args.no_model)
    on, auditor = audit(requests, args.recorded, tool=True, use_model=not args.no_model)
    metrics = score(cases, off, on, auditor, args.after_fix)
    text = report(requests, cases, off, on, auditor, metrics, args.run)
    print(text)
    errors = [f"{c}: {h.error}" for c, h in auditor.hunts.items() if h.error]
    for e in errors:
        print(f"warning: {e}", file=sys.stderr)
    if not args.recorded and not args.only:
        out = DEMO / "results"
        out.mkdir(exist_ok=True)
        (out / f"{args.run}{suffix}.md").write_text(text, encoding="utf-8")
        hunts = {c: {"outcome": h.outcome, "error": h.error, "calls": h.calls, "refused": h.refused,
                     "derived": h.derived, "late": h.late, "sweeps": h.sweeps, "request_ids": h.request_ids,
                     "copies": [c.uri for c in h.ghosts]} for c, h in sorted(auditor.hunts.items())}
        (out / f"{args.run}{suffix}.json").write_text(json.dumps(
            {"audit_at": at.isoformat() if at else None, "metrics": metrics, "off": off, "on": on, "hunts": hunts}, indent=1, sort_keys=True, default=list), encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
