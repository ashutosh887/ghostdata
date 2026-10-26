import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostdata.agent.ghost_hunt import GhostHunter, Hunt  # noqa: E402
from ghostdata.agent.tools.s3_ghosts import GhostFinder, RecordedFinder, linked_identifiers  # noqa: E402
from ghostdata.identity import email_hash  # noqa: E402

T0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
AUDIT = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)
MIRA = "mira.okafor@example.net"


class FakeS3:
    def __init__(self, objects, markers=(), holds=()):
        self.objects = objects
        self.markers = markers
        self.holds = set(holds)
        self.reads = []

    def client(self, name):
        return self

    def get_paginator(self, op):
        return self

    def paginate(self, Bucket, Prefix):
        versions = [{"Key": k, "VersionId": v, "Size": len(b), "IsLatest": latest, "LastModified": t}
                    for k, v, b, latest, t in self.objects if k.startswith(Prefix)]
        markers = [{"Key": k, "VersionId": f"dm-{k}", "IsLatest": True} for k in self.markers if k.startswith(Prefix)]
        return [{"Versions": versions, "DeleteMarkers": markers, "ResponseMetadata": {"RequestId": "REQ1"}}]

    def get_object(self, Bucket, Key, VersionId):
        self.reads.append((Key, VersionId))
        body = next(b for k, v, b, _, _ in self.objects if k == Key and v == VersionId)
        return {"Body": io.BytesIO(body), "ResponseMetadata": {"RequestId": f"GET-{VersionId}"}}

    def get_object_legal_hold(self, Bucket, Key, VersionId):
        return {"LegalHold": {"Status": "ON" if (Key, VersionId) in self.holds else "OFF"}}


def world():
    rows = [
        ("exports/a.csv", "v1", f"name,email\nMira Okafor,{MIRA}\nAda Lin,ada@example.org\n".encode(), False, T0),
        ("crm/b.json", "v2", json.dumps({"contact": {"email": MIRA, "alt_email": "mira.o@example.com"}}).encode(), True, T0),
        ("backups/c.txt", "v3", "row: mira.o@example.com".encode(), False, T0),
        ("hold/d.csv", "v4", f"{MIRA},ledger".encode(), True, T0),
        ("later/e.csv", "v5", MIRA.encode(), True, datetime(2026, 10, 27, tzinfo=timezone.utc)),
        ("decoy/f.csv", "v6", "Mira Okafor,mira.okafor@example.org,+1-555-0199".encode(), False, T0),
    ]
    return FakeS3(rows, markers=["exports/a.csv", "backups/c.txt", "decoy/f.csv"], holds=[("hold/d.csv", "v4")])


class Identities:
    def __init__(self):
        self.users = {"user_1": {"email": MIRA, "phone": "", "email_hash": email_hash(MIRA)}}
        self.owner = {MIRA: "user_1", email_hash(MIRA): "user_1", "ada@example.org": "user_2"}

    def resolve(self, email):
        return SimpleNamespace(user_id="user_1", keys=frozenset({"user_1", MIRA, email_hash(MIRA)}), emails=(MIRA,))

    def owners(self, keys):
        return {self.owner[k] for k in keys if k in self.owner}


def recorded(fake, tmp):
    return RecordedFinder(GhostFinder("demo", session=fake, comprehend=False), cache_dir=Path(tmp))


def hunter(fake, tmp):
    h = GhostHunter.__new__(GhostHunter)
    h.auditor = SimpleNamespace(identities=Identities())
    h.chat, h.finder, h.scope, h.model = None, recorded(fake, tmp), "", "m"
    return h


REQUEST = SimpleNamespace(case_id="case_1", email=MIRA, audit_at=AUDIT)


class GhostFinderTests(unittest.TestCase):
    def test_finds_version_hidden_by_delete_marker(self):
        s = GhostFinder("demo", session=world(), comprehend=False).search(world(), "exports/", {MIRA})
        self.assertEqual([(c.key, c.version_id, c.hidden_by_delete_marker) for c in s.copies], [("exports/a.csv", "v1", True)])
        self.assertIn(MIRA, s.copies[0].window)

    def test_same_name_different_email_is_not_a_match(self):
        s = GhostFinder("demo", session=world(), comprehend=False).search(world(), "decoy/", {MIRA, email_hash(MIRA)})
        self.assertEqual(s.copies, [])

    def test_legal_hold_is_read(self):
        s = GhostFinder("demo", session=world(), comprehend=False).search(world(), "hold/", {MIRA})
        self.assertTrue(s.copies[0].legal_hold)

    def test_linked_identifiers_share_a_record(self):
        text = json.dumps({"a": {"email": MIRA, "alt": "x@example.com"}, "b": {"email": "y@example.com"}})
        self.assertEqual(linked_identifiers(text, {MIRA}), ["x@example.com"])
        self.assertEqual(linked_identifiers("x@example.com\n" + MIRA, {MIRA}), [])

    def test_hash_inside_a_line_is_found(self):
        h = email_hash(MIRA)
        fake = FakeS3([("ml/f.jsonl", "v7", f'{{"h":"{h}","f":1}}\nrow,{h},0.3\n'.encode(), False, T0)])
        s = GhostFinder("demo", session=fake, comprehend=False).search(fake, "ml/", {h})
        self.assertEqual(len(s.copies), 1)

    def test_large_versions_are_skipped_and_labelled(self):
        big = FakeS3([("x/big.csv", "v9", b"a" * 2_000_000, True, T0)])
        s = GhostFinder("demo", session=big, comprehend=False).search(big, "x/", {MIRA})
        self.assertEqual(big.reads, [])
        self.assertIn("over the", s.skipped[0])

    def test_recording_replays_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = recorded(world(), tmp).search("t", "exports/", {MIRA})
            replay = RecordedFinder(None, offline=True, cache_dir=Path(tmp), bucket="demo")
            self.assertEqual(replay.search("t", "exports/", {MIRA}).copies[0].uri, live.copies[0].uri)


class GhostHunterTests(unittest.TestCase):
    def call(self, h, hunt, name, **args):
        return h.execute(REQUEST, {"name": name, "arguments": json.dumps(args)}, hunt, {MIRA, email_hash(MIRA)}, self.seen, "t")

    def setUp(self):
        self.seen = set()

    def test_foreign_identifier_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, hunt = hunter(world(), tmp), Hunt("case_1")
            out = json.loads(self.call(h, hunt, "find_ghost_copies", prefix="exports/", identifiers=["ada@example.org"]))
            self.assertIn("refused", out)
            self.assertEqual(hunt.copies, {})

    def test_repeat_call_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, hunt = hunter(world(), tmp), Hunt("case_1")
            self.call(h, hunt, "find_ghost_copies", prefix="exports/", identifiers=[MIRA])
            self.assertTrue(self.call(h, hunt, "find_ghost_copies", prefix="exports/", identifiers=[MIRA]).startswith("refused"))

    def test_chained_identifier_reaches_a_copy_one_search_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, hunt = hunter(world(), tmp), Hunt("case_1")
            out = json.loads(self.call(h, hunt, "find_ghost_copies", prefix="crm/", identifiers=[MIRA]))
            self.assertEqual(out["searchable_next"], ["mira.o@example.com"])
            self.call(h, hunt, "find_ghost_copies", prefix="backups/", identifiers=["mira.o@example.com"])
            self.assertIn(("backups/c.txt", "v3"), hunt.copies)

    def test_version_written_after_audit_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, hunt = hunter(world(), tmp), Hunt("case_1")
            self.call(h, hunt, "find_ghost_copies", prefix="later/", identifiers=[MIRA])
            self.assertEqual(hunt.copies, {})
            self.assertEqual(len(hunt.late), 1)

    def test_sweep_skips_folders_the_model_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            h, hunt = hunter(world(), tmp), Hunt("case_1")
            subject = {MIRA, email_hash(MIRA)}
            for folder in ["backups/", "crm/", "decoy/", "exports/", "hold/", "later/"]:
                self.call(h, hunt, "find_ghost_copies", prefix=folder, identifiers=sorted(subject))
            for folder in ["backups/", "decoy/", "exports/", "hold/", "later/"]:
                self.call(h, hunt, "find_ghost_copies", prefix=folder, identifiers=["mira.o@example.com"])
            h.sweep(REQUEST, hunt, subject, "t")
            self.assertEqual(hunt.sweeps, [("crm/", ["mira.o@example.com"])])

    def test_sweep_covers_what_the_model_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            hunt = hunter(world(), tmp).run(REQUEST)
            self.assertEqual(sorted(hunt.copies), [("backups/c.txt", "v3"), ("crm/b.json", "v2"),
                                                  ("exports/a.csv", "v1"), ("hold/d.csv", "v4")])
            self.assertEqual(hunt.by_model, set())


if __name__ == "__main__":
    unittest.main()
