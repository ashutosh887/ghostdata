from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostdata.agent import llm  # noqa: E402
from ghostdata.agent.documents import DocumentReader  # noqa: E402
from ghostdata.agent.intent import ModelIntent  # noqa: E402
from ghostdata.agent.llm import CacheMiss, ModelClient, ModelOutage, ModelUnavailable, SpendCapReached  # noqa: E402
from ghostdata.limits import SpendCaps  # noqa: E402
from ghostdata.observations import Observation  # noqa: E402
from ghostdata.planner import decide, plan  # noqa: E402
from ghostdata.state import state_at  # noqa: E402

SCHEMA = {"title": "t", "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
YES = '{"authorizes_deletion": "yes", "quoted_span": "delete my account", "language": "en", "reason": "r"}'
T = datetime(2026, 1, 1, tzinfo=timezone.utc)


class ScriptedClient(ModelClient):
    def __init__(self, replies, **kw):
        super().__init__(**kw)
        self.replies = list(replies)
        self.posts = 0

    def _post(self, role, model, payload):
        self.posts += 1
        self.ledger.add(model, role, calls=1, input_tokens=1000, output_tokens=100)
        return self.replies.pop(0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()


class SpendCapTest(Base):
    def test_defaults_and_env_overrides(self):
        self.assertEqual(SpendCaps.from_env(), SpendCaps())
        with mock.patch.dict(os.environ, {"GHOST_MAX_USD": "0.5", "GHOST_MAX_CALLS": "7", "GHOST_MAX_TOKENS": "99"}):
            self.assertEqual(SpendCaps.from_env(), SpendCaps(0.5, 7, 99))

    def test_call_cap_refuses_before_posting(self):
        client = ScriptedClient(['{"a": "1"}', '{"a": "2"}'], cache_dir=self.cache, caps=SpendCaps(calls=1))
        client.json("intent", "m", "s", "u1", SCHEMA)
        with self.assertRaises(SpendCapReached):
            client.json("intent", "m", "s", "u2", SCHEMA)
        self.assertEqual(client.posts, 1)

    def test_usd_cap_uses_the_price_table(self):
        model = next(iter(llm.PRICES))
        client = ScriptedClient([], cache_dir=self.cache, caps=SpendCaps(usd=0.01))
        client.ledger.add(model, "intent", calls=1, input_tokens=100_000_000)
        with self.assertRaises(SpendCapReached):
            client.json("intent", model, "s", "u", SCHEMA)
        self.assertEqual(client.posts, 0)

    def test_token_cap_counts_input_and_output(self):
        client = ScriptedClient([], cache_dir=self.cache, caps=SpendCaps(tokens=1100))
        client.ledger.add("m", "intent", calls=1, input_tokens=1000, output_tokens=100)
        with self.assertRaises(SpendCapReached):
            client.json("intent", "m", "s", "u", SCHEMA)

    def test_repair_retry_is_capped_too(self):
        client = ScriptedClient(["not json", '{"a": "y"}'], cache_dir=self.cache, caps=SpendCaps(calls=1))
        with self.assertRaises(SpendCapReached):
            client.json("intent", "m", "s", "u", SCHEMA)
        self.assertEqual(client.posts, 1)

    def test_cache_hits_are_free_after_the_cap(self):
        ScriptedClient(['{"a": "x"}'], cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)
        client = ScriptedClient([], cache_dir=self.cache, caps=SpendCaps(calls=0))
        self.assertEqual(client.json("intent", "m", "s", "u", SCHEMA), {"a": "x"})

    def test_cap_is_an_outage_not_a_cache_miss(self):
        self.assertTrue(issubclass(SpendCapReached, ModelOutage))
        self.assertFalse(issubclass(CacheMiss, ModelOutage))
        self.assertTrue(issubclass(CacheMiss, ModelUnavailable))


class IntentFallbackTest(Base):
    def test_missing_key_falls_back_to_the_rule_and_is_recorded(self):
        client = ModelClient(cache_dir=self.cache)
        intent = ModelIntent(client)("Please delete my account and everything you hold on me.")
        self.assertTrue(intent.authorizes_deletion)
        self.assertEqual(intent.source, "rules-fallback")
        self.assertEqual([role for role, _, _ in client.fallbacks], ["intent"])

    def test_fallback_keeps_the_rule_refusal(self):
        client = ModelClient(cache_dir=self.cache)
        intent = ModelIntent(client)("Do not delete anything, I only want a copy of my data.")
        self.assertFalse(intent.authorizes_deletion)
        self.assertEqual(intent.source, "rules-fallback")

    def test_spent_cap_falls_back(self):
        client = ScriptedClient([YES], cache_dir=self.cache, caps=SpendCaps(calls=0))
        intent = ModelIntent(client)("Please delete my account.")
        self.assertEqual((intent.source, client.posts), ("rules-fallback", 0))

    def test_live_answer_is_not_a_fallback(self):
        client = ScriptedClient([YES], cache_dir=self.cache)
        intent = ModelIntent(client)("Please delete my account.")
        self.assertEqual((intent.source, client.fallbacks), ("model", []))

    def test_offline_cache_miss_still_stops(self):
        client = ModelClient(offline=True, cache_dir=self.cache)
        with self.assertRaises(CacheMiss):
            ModelIntent(client)("Please delete my account.")
        self.assertEqual(client.fallbacks, [])


class Unreadable(DocumentReader):
    def __init__(self, client):
        self.client = client
        self.unread, self.flags, self.contradicted = {}, {}, {}

    def read(self, corpus, obs):
        raise ModelOutage("no key")


class DocumentFallbackTest(Base):
    def unread_observation(self):
        doc = Observation("F1", T, T, "support", "ticket_1", "image", present=True, where="image F1 shows TCK-1")
        corpus = SimpleNamespace(observations=[doc])
        reader = Unreadable(ModelClient(cache_dir=self.cache))
        reader.apply(corpus)
        return reader, corpus.observations[0]

    def test_unread_document_is_assumed_to_expose_its_record(self):
        reader, o = self.unread_observation()
        self.assertEqual((o.present, o.exposed, o.active), (True, True, True))
        self.assertEqual(reader.unread, {"F1": "ticket_1"})
        self.assertEqual([r for r, _, _ in reader.client.fallbacks], ["vision"])

    def test_unread_document_never_certifies_complete(self):
        _, o = self.unread_observation()
        st = state_at("ticket_1", "support", [o], [], [], frozenset(), T, T)
        for action in ("DELETE", "REDACT", "ANONYMIZE", "DISABLE_FLOW", "BLOCK_RESTORE"):
            status, _ = plan([decide(st, action)], T)
            self.assertEqual(status, "INCOMPLETE", action)


if __name__ == "__main__":
    unittest.main()
