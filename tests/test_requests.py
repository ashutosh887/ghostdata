from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostdata.dataset import Request, load_requests, parse_time  # noqa: E402
from ghostdata.ingest import load_corpus  # noqa: E402
from ghostdata.resolver import Auditor  # noqa: E402

HEADER = "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n"


def request(email: str, text: str = "Please delete my account.") -> Request:
    return Request("case_9001", email, parse_time("2026-09-01T00:00:00Z"), "COMPLETE",
                   parse_time("2026-09-02T00:00:00Z"), parse_time("2026-09-03T00:00:00Z"), text)


class RequestHandlingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auditor = Auditor(load_corpus())

    def test_unknown_email_is_not_applicable_without_steps(self):
        case = self.auditor.audit(request("nobody.here@example.com"))
        self.assertEqual((case.status, case.steps), ("NOT_APPLICABLE", []))
        self.assertIn("no current or historical identity", case.note)

    def test_empty_email_is_not_applicable(self):
        self.assertEqual(self.auditor.audit(request("")).status, "NOT_APPLICABLE")

    def test_non_deletion_text_has_no_steps(self):
        case = self.auditor.audit(request("nobody.here@example.com", "Please send me my invoices."))
        self.assertEqual((case.status, case.steps, case.note), ("NOT_APPLICABLE", [], ""))

    def test_audit_before_request_is_not_applicable(self):
        known = load_requests(Path(__file__).resolve().parents[1] / "dataset" / "deletion_requests.csv")[0]
        bad = Request("case_9002", known.email, known.audit_at, "COMPLETE", known.audit_at, known.requested_at,
                      "Please delete my account.")
        case = self.auditor.audit(bad)
        self.assertEqual((case.status, case.steps), ("NOT_APPLICABLE", []))
        self.assertIn("before requested_at", case.note)

    def test_bad_rows_do_not_stop_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.csv"
            path.write_text(HEADER + "case_1,a@b.com,2026-09-05T00:00:00Z,COMPLETE,2026-09-06T00:00:00Z,"
                                     "2026-09-01T00:00:00Z,Please delete my account.\n", encoding="utf-8")
            self.assertEqual(len(load_requests(path)), 1)


if __name__ == "__main__":
    unittest.main()
