from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostdata.dataset import DATASET_DIR, evidence_times, load_requests, read_csv  # noqa: E402
from ghostdata.validate import validate_output  # noqa: E402

REQUESTS = load_requests(DATASET_DIR / "sample_deletion_requests.csv")
EVIDENCE_AT = evidence_times()
GOLD = read_csv(DATASET_DIR / "sample_output.csv")


def first(status: str) -> int:
    return next(i for i, r in enumerate(GOLD) if r["deletion_status"] == status)


class ValidatorTest(unittest.TestCase):
    def run_rows(self, rows: list[dict]):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(["case_id", "deletion_status", "steps_json"])
                for r in rows:
                    writer.writerow([r["case_id"], r["deletion_status"], r["steps_json"]])
            return validate_output(path, REQUESTS, EVIDENCE_AT)

    def mutate(self, index: int, fn) -> list[dict]:
        rows = [dict(r) for r in GOLD]
        steps = json.loads(rows[index]["steps_json"])
        result = fn(rows[index], steps)
        rows[index]["steps_json"] = json.dumps(steps if result is None else result)
        return rows

    def assert_rejected(self, rows: list[dict]) -> None:
        self.assertFalse(self.run_rows(rows).ok)

    def test_sample_answers_pass(self):
        report = self.run_rows(GOLD)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_citation_after_audit_is_rejected(self):
        index = first("COMPLETE")
        audit_at = REQUESTS[index].audit_at
        late = next(e for e, t in sorted(EVIDENCE_AT.items()) if t > audit_at)

        def fn(row, steps):
            steps[0]["evidence_id"] = late
        self.assert_rejected(self.mutate(index, fn))

    def test_missing_row(self):
        self.assert_rejected(GOLD[:-1])

    def test_unsorted_rows(self):
        self.assert_rejected([GOLD[1], GOLD[0]] + GOLD[2:])

    def test_step_numbers_must_be_consecutive(self):
        def fn(row, steps):
            steps[0]["step_no"] = 2
        self.assert_rejected(self.mutate(first("INCOMPLETE"), fn))

    def test_wrong_state_for_operation(self):
        def fn(row, steps):
            steps[0]["state"] = "ABSENT"
        self.assert_rejected(self.mutate(first("INCOMPLETE"), fn))

    def test_reversed_order(self):
        def fn(row, steps):
            steps.reverse()
            for no, s in enumerate(steps, start=1):
                s["step_no"] = no
        self.assert_rejected(self.mutate(first("INCOMPLETE"), fn))

    def test_finding_without_evidence(self):
        def fn(row, steps):
            steps[0]["evidence_id"] = ""
        self.assert_rejected(self.mutate(first("INCOMPLETE"), fn))

    def test_remediation_with_evidence(self):
        def fn(row, steps):
            for s in steps:
                if s["phase"] == "REMEDIATION":
                    s["evidence_id"] = "evidence_01"
                    break
        self.assert_rejected(self.mutate(first("INCOMPLETE"), fn))

    def test_complete_with_finding(self):
        def fn(row, steps):
            return [dict(steps[0], phase="FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT")]
        self.assert_rejected(self.mutate(first("COMPLETE"), fn))

    def test_unknown_evidence(self):
        def fn(row, steps):
            steps[0]["evidence_id"] = "evidence_999"
        self.assert_rejected(self.mutate(first("COMPLETE"), fn))

    def test_not_applicable_with_steps(self):
        rows = [dict(r) for r in GOLD]
        rows[0]["deletion_status"] = "NOT_APPLICABLE"
        self.assert_rejected(rows)

    def test_extra_field(self):
        def fn(row, steps):
            steps[0]["note"] = "x"
        self.assert_rejected(self.mutate(first("COMPLETE"), fn))


if __name__ == "__main__":
    unittest.main()
