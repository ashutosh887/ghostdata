from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation"))

from ghostdata.dataset import DATASET_DIR, read_csv  # noqa: E402
from score import parse_rows, score_case, summarize  # noqa: E402
from splits import HOLDOUT, draw_holdout  # noqa: E402

GOLD = parse_rows(read_csv(DATASET_DIR / "sample_output.csv"))


class ScoreTest(unittest.TestCase):
    def test_gold_scores_perfect(self):
        results = [score_case(c, s, steps, s, steps) for c, (s, steps) in GOLD.items()]
        summary = summarize(results)
        self.assertEqual(summary["step_prf"], (1.0, 1.0, 1.0))
        self.assertTrue(summary["exact_match"].startswith("32/32"))
        self.assertEqual(summary["sequence_similarity"], 1.0)

    def test_reversed_steps_lose_order_not_recall(self):
        status, steps = GOLD["case_11"]
        r = score_case("case_11", status, steps, status, list(reversed(steps)))
        self.assertEqual(r.tp, len(steps))
        self.assertFalse(r.order_ok)
        self.assertFalse(r.exact)

    def test_false_complete_counted(self):
        status, steps = GOLD["case_05"]
        r = score_case("case_05", status, steps, "COMPLETE", [])
        self.assertEqual(summarize([r])["false_complete"], 1)

    def test_holdout_matches_seeded_draw(self):
        self.assertEqual(draw_holdout({c: s for c, (s, _) in GOLD.items()}), HOLDOUT)


if __name__ == "__main__":
    unittest.main()
