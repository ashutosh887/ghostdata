from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit.state import Proof, latest  # noqa: E402


def at(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=timezone.utc)


def event(hour: int, value: bool, source: str):
    return at(hour), value, Proof(source, at(hour), at(hour), source)


class LatestTest(unittest.TestCase):
    def test_newest_value_wins(self):
        value, proofs = latest([event(1, True, "a"), event(2, False, "b")])
        self.assertFalse(value)
        self.assertEqual([p.source_id for p in proofs], ["b"])

    def test_tie_keeps_the_present_proof(self):
        value, proofs = latest([event(1, False, "a"), event(2, False, "b"), event(2, True, "c")])
        self.assertTrue(value)
        self.assertEqual([p.source_id for p in proofs], ["c"])

    def test_agreeing_run_since_last_change(self):
        value, proofs = latest([event(1, True, "a"), event(2, False, "b"), event(3, True, "c"), event(4, True, "d")])
        self.assertTrue(value)
        self.assertEqual([p.source_id for p in proofs], ["c", "d"])


if __name__ == "__main__":
    unittest.main()
