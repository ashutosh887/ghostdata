from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluation"))

import check  # noqa: E402

PINNED = json.loads(check.BASELINE.read_text(encoding="utf-8"))


class RegressionGateTest(unittest.TestCase):
    def test_baseline_has_every_gated_metric(self):
        for k in ("false_complete", "status_accuracy", "exact_match", "step_f1", "field_accuracy"):
            self.assertIn(k, PINNED)
        self.assertEqual(PINNED["false_complete"], 0)

    def test_pinned_score_passes(self):
        self.assertEqual(check.regressions(copy.deepcopy(PINNED), PINNED), [])

    def test_improvement_passes(self):
        better = copy.deepcopy(PINNED)
        better["exact_match"] += 0.05
        better["field_accuracy"]["resource_id"] += 0.01
        self.assertEqual(check.regressions(better, PINNED), [])

    def test_every_single_drop_fails(self):
        for key in ("status_accuracy", "exact_match", "step_f1", "sequence_order_ok", "sequence_similarity"):
            worse = copy.deepcopy(PINNED)
            worse[key] -= 0.001
            self.assertEqual(len(check.regressions(worse, PINNED)), 1, key)
        for field in PINNED["field_accuracy"]:
            worse = copy.deepcopy(PINNED)
            worse["field_accuracy"][field] -= 0.001
            self.assertEqual(len(check.regressions(worse, PINNED)), 1, field)

    def test_false_complete_fails_even_with_better_scores(self):
        worse = copy.deepcopy(PINNED)
        worse["false_complete"] = 1
        worse["exact_match"] = 1.0
        self.assertTrue(check.regressions(worse, PINNED))

    def test_missing_metric_fails(self):
        worse = copy.deepcopy(PINNED)
        del worse["step_f1"]
        del worse["field_accuracy"]["phase"]
        self.assertEqual(len(check.regressions(worse, PINNED)), 2)

    def test_scorer_summary_maps_to_metrics(self):
        summary = {"false_complete": 0, "status_accuracy": "22/22 (1.000)", "exact_match": "14/22 (0.636)",
                   "step_prf": [1, 1, 0.9], "sequence_order_ok": "0/0", "sequence_similarity": 0.9,
                   "field_accuracy": {"phase": 0.9}}
        m = check.metrics(summary)
        self.assertAlmostEqual(m["exact_match"], 14 / 22)
        self.assertEqual((m["step_f1"], m["sequence_order_ok"]), (0.9, 1.0))


if __name__ == "__main__":
    unittest.main()
