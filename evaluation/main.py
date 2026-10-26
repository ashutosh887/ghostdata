from __future__ import annotations

import argparse
import json
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation"))

from ghostdata.dataset import DATASET_DIR, load_requests, read_csv  # noqa: E402
from baselines import BASELINES  # noqa: E402
from score import parse_rows, score_case, summarize  # noqa: E402
from splits import HOLDOUT, draw_holdout, split_of  # noqa: E402

HISTORY = ROOT / "evaluation" / "history.md"


def predict(system: str, requests, offline: bool = False) -> dict:
    if system in BASELINES:
        fn = BASELINES[system]
        rows = [(r.case_id, *fn(r)) for r in requests]
    else:
        spec = importlib.util.spec_from_file_location("solver", ROOT / "cli" / "audit.py")
        solver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(solver)
        rows, _ = solver.run(requests, use_model=system == "agent", offline=offline)
    return parse_rows([{"case_id": c, "deletion_status": s, "steps_json": j} for c, s, j in rows])


def print_summary(title: str, summary: dict) -> None:
    p, r, f = summary["step_prf"]
    pn, rn, fn = summary["step_prf_no_evidence"]
    print(f"== {title} ({summary['cases']} cases)")
    print(f"false COMPLETE            {summary['false_complete']}")
    print(f"steps on NOT_APPLICABLE   {summary['unauthorised_steps']}")
    print(f"status accuracy           {summary['status_accuracy']}")
    print(f"exact steps_json          {summary['exact_match']}")
    print(f"step P / R / F1           {p:.3f} / {r:.3f} / {f:.3f}   ({summary['steps']})")
    print(f"step F1 without evidence  {fn:.3f}")
    print(f"field accuracy            {summary['field_accuracy']}")
    print(f"sequence order agrees     {summary['sequence_order_ok']}")
    print(f"sequence similarity       {summary['sequence_similarity']}")
    for s, v in summary["per_class"].items():
        print(f"  {s:<15} precision {v['precision']:<16} recall {v['recall']}")


def record(label: str, system: str, split: str, summary: dict) -> None:
    if not HISTORY.exists():
        HISTORY.write_text(
            "# Evaluation history\n\nOne row per pinned scorer run on the sample cases.\n\n"
            "| When (UTC) | Label | System | Split | Cases | False COMPLETE | Status | Exact | Step F1 | F1 no evidence | Order ok |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    row = (f"| {when} | {label} | {system} | {split} | {summary['cases']} | {summary['false_complete']} | "
           f"{summary['status_accuracy']} | {summary['exact_match']} | {summary['step_prf'][2]:.3f} | "
           f"{summary['step_prf_no_evidence'][2]:.3f} | {summary['sequence_order_ok']} |\n")
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score predictions against the sample answers")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--system", default="agent", choices=["agent", "rules", *BASELINES])
    parser.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    parser.add_argument("--show", action="store_true", help="print missing and extra steps per case")
    parser.add_argument("--record", metavar="LABEL", help="append the result to history.md")
    parser.add_argument("--json", action="store_true", help="print the summary as one JSON line")
    args = parser.parse_args()

    gold = parse_rows(read_csv(DATASET_DIR / "sample_output.csv"))
    if draw_holdout({c: s for c, (s, _) in gold.items()}) != HOLDOUT:
        raise SystemExit("holdout list no longer matches its seeded draw")

    requests = [r for r in load_requests(DATASET_DIR / "sample_deletion_requests.csv")
                if args.split == "all" or split_of(r.case_id) == args.split]
    pred = predict(args.system, requests, args.offline)

    results = []
    for r in requests:
        g_status, g_steps = gold[r.case_id]
        p_status, p_steps = pred[r.case_id]
        results.append(score_case(r.case_id, g_status, g_steps, p_status, p_steps))

    if args.show:
        for res in results:
            if res.exact:
                continue
            print(f"-- {res.case_id} gold {res.gold_status} pred {res.pred_status}")
            for k in res.missing:
                print(f"   missing {k}")
            for k in res.extra:
                print(f"   extra   {k}")

    summary = summarize(results)
    if args.json:
        print(json.dumps(summary))
        return 0
    print_summary(f"{args.system} on {args.split}", summary)
    if args.record:
        record(args.record, args.system, args.split, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
