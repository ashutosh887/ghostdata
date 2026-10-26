from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostdata.ingest import load_corpus  # noqa: E402
from ghostdata.ingest.logs import parse_line  # noqa: E402

CORPUS = load_corpus()


def obs(rid: str, source: str | None = None):
    return [o for o in CORPUS.observations if o.resource_id == rid and (source is None or o.source_id == source)]


class IngestTest(unittest.TestCase):
    def test_every_file_is_read(self):
        self.assertEqual(sum(s["files"] for k, s in CORPUS.stats.items() if k != "activity"), 94)

    def test_decoy_service_lookups_are_dropped(self):
        self.assertEqual(CORPUS.stats["log"]["unattributed"], 300)
        self.assertFalse([o for o in CORPUS.observations if o.source_id == "evidence_53"])

    def test_trace_join_puts_identifier_and_state_together(self):
        o = obs("account_7947", "evidence_16")[0]
        self.assertIn("l.nascimento40@gmail.com", o.keys)
        self.assertFalse(o.present)

    def test_old_email_hash_in_correlation_key(self):
        old = hashlib.sha256(b"minjun.kim90@gmail.com").hexdigest()
        o = obs("analytics_9914", "evidence_01")[0]
        self.assertIn(old, o.keys)
        self.assertTrue(o.exposed)

    def test_lookalike_email_is_its_own_key(self):
        keys = set().union(*(o.keys for o in obs("search_1874")))
        self.assertIn("g.silva76.jr@gmail.com", keys)
        self.assertNotIn("g.silva76@gmail.com", keys)

    def test_replica_only_row_is_present(self):
        rows = obs("account_005", "evidence_54")
        self.assertEqual(len(rows), 1)
        self.assertIn("failover_replica", rows[0].where)
        primary = [s for s in CORPUS.snapshots if s.source_id == "evidence_54"][0]
        self.assertTrue(primary.covers("account_service"))

    def test_support_replica_contradicts_deletion_claim(self):
        o = obs("support_002", "evidence_61")[0]
        self.assertTrue(o.present)
        self.assertIn("nadia.ionescu@yahoo.com", o.keys)

    def test_inventory_scope_limits_absence(self):
        scoped = [s for s in CORPUS.snapshots if s.source_id == "evidence_90"]
        self.assertEqual([sorted(s.systems) for s in scoped], [["account_service"]])

    def test_redacted_support_message_is_not_exposed(self):
        o = obs("support_6334", "evidence_06")[0]
        self.assertTrue(o.present)
        self.assertFalse(o.exposed)

    def test_identity_links(self):
        links = {o.resource_id: o.keys for o in CORPUS.observations if o.kind == "link"}
        self.assertEqual(len(links), 12)
        self.assertIn("user_07", links["object_19"])

    def test_unknown_log_line_fails_loudly(self):
        with self.assertRaises(ValueError):
            parse_line("x", 1, "not a log line")


if __name__ == "__main__":
    unittest.main()
