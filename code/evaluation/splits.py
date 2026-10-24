from __future__ import annotations

import random

SEED = 20261024
HOLDOUT_SIZE = {"COMPLETE": 3, "INCOMPLETE": 7}

# Frozen on 2026-10-24, before any resolver code existed. Scored once, after the last change.
HOLDOUT = (
    "case_02", "case_03", "case_05", "case_06", "case_07",
    "case_11", "case_14", "case_22", "case_30", "case_31",
)


def draw_holdout(gold_status: dict[str, str]) -> tuple[str, ...]:
    rng = random.Random(SEED)
    picked = []
    for status, k in HOLDOUT_SIZE.items():
        ids = sorted(c for c, s in gold_status.items() if s == status)
        picked += rng.sample(ids, k)
    return tuple(sorted(picked))


def split_of(case_id: str) -> str:
    return "holdout" if case_id in HOLDOUT else "dev"
