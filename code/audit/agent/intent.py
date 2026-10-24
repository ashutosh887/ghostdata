from __future__ import annotations

import unicodedata

from ..config import MODELS, PROMPT_DIR
from ..intent import Intent, rule_intent
from .guard import fence, injection_hits
from .llm import ModelClient

SCHEMA = {
    "title": "intent",
    "type": "object",
    "properties": {
        "authorizes_deletion": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "quoted_span": {"type": "string"},
        "language": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["authorizes_deletion", "quoted_span", "language", "reason"],
    "additionalProperties": False,
}


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().replace("’", "'").split())


class ModelIntent:
    """The model reads the request; code accepts a refusal only when the quoted words are really in the text."""

    def __init__(self, client: ModelClient, model: str = MODELS["intent"]):
        self.client = client
        self.model = model
        self.system = (PROMPT_DIR / "intent.md").read_text(encoding="utf-8")
        self.flags: dict[str, list[str]] = {}

    def __call__(self, text: str) -> Intent:
        hits = injection_hits(text)
        if hits:
            self.flags[text] = hits
        answer = self.client.json("intent", self.model, self.system, fence("request", text), SCHEMA, max_tokens=300)
        verdict = answer["authorizes_deletion"]
        span = answer["quoted_span"].strip()
        grounded = bool(span) and _norm(span) in _norm(text)
        if verdict == "yes" and grounded:
            return Intent(True, f'model quotes "{span}" ({answer["language"]})', "model")
        if verdict == "no" and grounded:
            return Intent(False, f'model quotes "{span}" ({answer["language"]})', "model")
        fallback = rule_intent(text)
        why = "unclear" if verdict == "unclear" else f"ungrounded {verdict}"
        return Intent(fallback.authorizes_deletion, f"model {why}; keyword rule {fallback.reason}", "model+rules")
