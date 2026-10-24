from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit.agent import llm  # noqa: E402
from audit.agent.llm import ModelClient, ModelUnavailable  # noqa: E402

SCHEMA = {"title": "t", "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


class ScriptedClient(ModelClient):
    """Replays a list of raw model replies in place of the network."""

    def __init__(self, replies, **kw):
        super().__init__(**kw)
        self.replies = list(replies)
        self.posts = 0

    def _post(self, role, model, payload):
        self.posts += 1
        return self.replies.pop(0)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"busy"))


class ModelClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_answer_is_cached_and_replayed_offline(self):
        ScriptedClient(['{"a": "x"}'], cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)
        replay = ScriptedClient([], offline=True, cache_dir=self.cache)
        self.assertEqual(replay.json("intent", "m", "s", "u", SCHEMA), {"a": "x"})
        self.assertEqual(replay.posts, 0)
        self.assertEqual(replay.ledger.by_role["intent"].cache_hits, 1)

    def test_offline_miss_stops_instead_of_guessing(self):
        with self.assertRaises(ModelUnavailable):
            ScriptedClient([], offline=True, cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)

    def test_changed_prompt_is_a_cache_miss(self):
        ScriptedClient(['{"a": "x"}'], cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)
        with self.assertRaises(ModelUnavailable):
            ScriptedClient([], offline=True, cache_dir=self.cache).json("intent", "m", "s2", "u", SCHEMA)

    def test_invalid_json_is_repaired_once(self):
        client = ScriptedClient(["not json", '{"a": "y"}'], cache_dir=self.cache)
        self.assertEqual(client.json("intent", "m", "s", "u", SCHEMA), {"a": "y"})
        self.assertEqual(client.posts, 2)
        self.assertEqual(client.ledger.by_role["intent"].repairs, 1)

    def test_twice_invalid_json_raises(self):
        client = ScriptedClient(["no", "still no"], cache_dir=self.cache)
        with self.assertRaises(ValueError):
            client.json("intent", "m", "s", "u", SCHEMA)
        self.assertFalse(any(self.cache.rglob("*.json")))

    def test_missing_key_is_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelUnavailable):
                ModelClient(cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)

    def test_throttling_is_retried_then_fails_loudly(self):
        with mock.patch.dict(os.environ, {llm.KEY_VAR: "k"}), \
                mock.patch.object(llm.urllib.request, "urlopen", side_effect=http_error(429)) as call, \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(ModelUnavailable):
                ModelClient(cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)
        self.assertEqual(call.call_count, llm.MAX_RETRIES)

    def test_client_error_is_not_retried(self):
        client = ModelClient(cache_dir=self.cache)
        with mock.patch.dict(os.environ, {llm.KEY_VAR: "k"}), \
                mock.patch.object(llm.urllib.request, "urlopen", side_effect=http_error(400)) as call, \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(ModelUnavailable):
                client.json("intent", "m", "s", "u", SCHEMA)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(client.ledger.by_role["intent"].failures, 1)

    def test_timeout_is_retried(self):
        with mock.patch.dict(os.environ, {llm.KEY_VAR: "k"}), \
                mock.patch.object(llm.urllib.request, "urlopen", side_effect=TimeoutError("slow")) as call, \
                mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(ModelUnavailable):
                ModelClient(cache_dir=self.cache).json("intent", "m", "s", "u", SCHEMA)
        self.assertEqual(call.call_count, llm.MAX_RETRIES)


if __name__ == "__main__":
    unittest.main()
