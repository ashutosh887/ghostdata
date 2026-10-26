from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from ghostdata.schema import STATUSES, STEP_FIELDS

KEY_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
FIELDS = tuple(f for f in STEP_FIELDS if f != "step_no")


def step_key(step: dict, with_evidence: bool = True) -> tuple:
    return tuple(step[f] for f in KEY_FIELDS if with_evidence or f != "evidence_id")


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        cur = [i]
        for j, y in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


@dataclass
class CaseResult:
    case_id: str
    gold_status: str
    pred_status: str
    exact: bool
    tp: int
    pred_n: int
    gold_n: int
    tp_no_evidence: int
    field_hits: Counter
    positions: int
    order_ok: bool
    sequence_similarity: float
    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)


def score_case(case_id: str, gold_status: str, gold_steps: list, pred_status: str, pred_steps: list) -> CaseResult:
    gold_keys = Counter(step_key(s) for s in gold_steps)
    pred_keys = Counter(step_key(s) for s in pred_steps)
    tp = sum((gold_keys & pred_keys).values())
    tp_ne = sum((Counter(step_key(s, False) for s in gold_steps) & Counter(step_key(s, False) for s in pred_steps)).values())

    positions = max(len(gold_steps), len(pred_steps))
    hits = Counter()
    for g, p in zip(gold_steps, pred_steps):
        for f in FIELDS:
            hits[f] += g[f] == p[f]

    g_seq = [step_key(s) for s in gold_steps]
    p_seq = [step_key(s) for s in pred_steps]
    common = set(g_seq) & set(p_seq)
    order_ok = bool(common) and [k for k in g_seq if k in common] == [k for k in p_seq if k in common]
    similarity = 1.0 if positions == 0 else 1 - edit_distance(g_seq, p_seq) / positions

    return CaseResult(
        case_id=case_id,
        gold_status=gold_status,
        pred_status=pred_status,
        exact=gold_status == pred_status and g_seq == p_seq,
        tp=tp,
        pred_n=len(pred_steps),
        gold_n=len(gold_steps),
        tp_no_evidence=tp_ne,
        field_hits=hits,
        positions=positions,
        order_ok=order_ok,
        sequence_similarity=similarity,
        missing=sorted((gold_keys - pred_keys).elements()),
        extra=sorted((pred_keys - gold_keys).elements()),
    )


def ratio(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.3f})" if d else f"{n}/0"


def f1(tp: int, pred: int, gold: int) -> tuple[float, float, float]:
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def summarize(results: list[CaseResult]) -> dict:
    n = len(results)
    tp = sum(r.tp for r in results)
    pred = sum(r.pred_n for r in results)
    gold = sum(r.gold_n for r in results)
    tp_ne = sum(r.tp_no_evidence for r in results)
    positions = sum(r.positions for r in results)
    per_class = {}
    for s in STATUSES:
        t = sum(r.gold_status == s and r.pred_status == s for r in results)
        per_class[s] = {
            "precision": ratio(t, sum(r.pred_status == s for r in results)),
            "recall": ratio(t, sum(r.gold_status == s for r in results)),
        }
    return {
        "cases": n,
        "false_complete": sum(r.pred_status == "COMPLETE" and r.gold_status != "COMPLETE" for r in results),
        "unauthorised_steps": sum(r.gold_status == "NOT_APPLICABLE" and r.pred_n > 0 for r in results),
        "status_accuracy": ratio(sum(r.gold_status == r.pred_status for r in results), n),
        "exact_match": ratio(sum(r.exact for r in results), n),
        "step_prf": f1(tp, pred, gold),
        "step_prf_no_evidence": f1(tp_ne, pred, gold),
        "steps": {"matched": tp, "predicted": pred, "gold": gold},
        "field_accuracy": {f: round(sum(r.field_hits[f] for r in results) / positions, 3) if positions else 0.0
                           for f in FIELDS},
        "sequence_order_ok": ratio(sum(r.order_ok for r in results), n),
        "sequence_similarity": round(sum(r.sequence_similarity for r in results) / n, 3) if n else 0.0,
        "per_class": per_class,
    }


def parse_rows(rows: list[dict]) -> dict[str, tuple[str, list]]:
    return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"] or "[]")) for r in rows}
