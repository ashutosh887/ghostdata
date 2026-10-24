from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

from ..config import CACHE_DIR, ENDPOINT, KEY_VAR, MAX_RETRIES, PRICES, PROVIDER, REGION_VAR, TIMEOUT_SECONDS


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class ModelStats:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    repairs: int = 0
    failures: int = 0
    seconds: float = 0.0


@dataclass
class Ledger:
    """Every model request the run made, per model and per role."""

    by_model: dict = field(default_factory=lambda: defaultdict(ModelStats))
    by_role: dict = field(default_factory=lambda: defaultdict(ModelStats))
    role_models: dict = field(default_factory=lambda: defaultdict(set))

    def add(self, model: str, role: str, **delta) -> None:
        self.role_models[role].add(model)
        for stats in (self.by_model[model], self.by_role[role]):
            for k, v in delta.items():
                setattr(stats, k, getattr(stats, k) + v)

    def cost(self, model: str) -> float:
        s = self.by_model[model]
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        return (s.input_tokens * price_in + s.output_tokens * price_out) / 1_000_000

    def report(self, requests: int, investigations: list, when: str) -> str:
        """usage_report.md for the run that wrote output.csv."""
        models = sorted(self.by_model)
        total = ModelStats()
        for m in models:
            for k, v in vars(self.by_model[m]).items():
                setattr(total, k, getattr(total, k) + v)
        cost = sum(self.cost(m) for m in models)
        tokens = total.input_tokens + total.output_tokens
        lines = [
            "# Token usage and cost",
            "",
            f"Final full-dataset run that wrote `output.csv`: {requests} requests, {when}.",
            f"Provider: {PROVIDER}. Every answer was requested live in this run (cache reads off), then stored in",
            "`code/cache/` so `python3 code/main.py --offline` replays it with no key and no cost.",
            "",
            "## Per model",
            "",
            "| Model | Roles | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) | Price in / out per 1M |",
            "|---|---|---|---|---|---|---|---|",
        ]
        roles = {m: sorted(r for r, s in self.by_role.items() if s.calls and m in self.role_models.get(r, ())) for m in models}
        for m in models:
            s = self.by_model[m]
            pi, po = PRICES.get(m, (0.0, 0.0))
            lines.append(f"| `{m}` | {', '.join(roles[m]) or '-'} | {s.calls} | {s.input_tokens:,} | {s.output_tokens:,} | "
                         f"{s.input_tokens + s.output_tokens:,} | {self.cost(m):.4f} | {pi:.2f} / {po:.2f} |")
        lines.append(f"| **All models** | | **{total.calls}** | **{total.input_tokens:,}** | **{total.output_tokens:,}** | "
                     f"**{tokens:,}** | **{cost:.4f}** | |")
        lines += [
            "",
            "## Per role",
            "",
            "| Role | Calls | Input tokens | Output tokens | JSON repairs | Failures |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(self.by_role):
            s = self.by_role[r]
            lines.append(f"| {r} | {s.calls} | {s.input_tokens:,} | {s.output_tokens:,} | {s.repairs} | {s.failures} |")
        flagged = len(investigations)
        lines += [
            "",
            "## Per request",
            "",
            f"- Total tokens: {tokens:,}; average per request: {tokens / requests:,.0f}.",
            f"- Estimated cost: ${cost:.4f} in total; ${cost / requests:.6f} per request.",
            f"- Model calls: {total.calls} in total; {total.calls / requests:.2f} per request.",
            f"- Intent is classified once per distinct request text; documents are read once each; the investigator runs only",
            f"  on the {flagged} cases the resolver flagged, at most 6 rounds each.",
            "",
            "Costs are estimates: the endpoint returns token counts but no price, so the table applies the Amazon Bedrock",
            "on-demand prices listed in `code/audit/config.py`.",
        ]
        return "\n".join(lines) + "\n"


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ModelClient:
    """JSON-only chat client with a content-addressed cache.

    A cache hit replays the stored answer and costs nothing. In offline mode a miss is an error, so a
    replayed run either matches the recorded run exactly or stops. Online, a missing key is an error too:
    the run never falls back to a rules-only answer without saying so.
    """

    def __init__(self, offline: bool = False, fresh: bool = False, cache_dir=CACHE_DIR / "llm",
                 ledger: Ledger | None = None):
        self.offline = offline
        self.fresh = fresh
        self.cache_dir = cache_dir
        self.ledger = ledger or Ledger()

    def json(self, role: str, model: str, system: str, user: list | str, schema: dict, max_tokens: int = 800) -> dict:
        content = user if isinstance(user, list) else [{"type": "text", "text": user}]
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema.get("title", "answer"), "strict": True, "schema": schema}},
        }
        key = _key(payload)
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists() and not self.fresh:
            self.ledger.add(model, role, cache_hits=1)
            return json.loads(path.read_text(encoding="utf-8"))["answer"]
        if self.offline:
            raise ModelUnavailable(f"offline replay has no cached {role} answer ({key[:12]}); run online once to record it")

        answer, raw = self._ask_json(role, model, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"role": role, "model": model, "answer": answer, "raw": raw},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return answer

    def _ask_json(self, role: str, model: str, payload: dict) -> tuple[dict, str]:
        raw = self._post(role, model, payload)
        try:
            return json.loads(raw), raw
        except json.JSONDecodeError:
            self.ledger.add(model, role, repairs=1)
            retry = json.loads(json.dumps(payload))
            retry["messages"].append({"role": "assistant", "content": raw})
            retry["messages"].append({"role": "user", "content": "That was not valid JSON for the schema. Reply with the JSON object only."})
            raw = self._post(role, model, retry)
            return json.loads(raw), raw

    def _post(self, role: str, model: str, payload: dict) -> str:
        token = os.environ.get(KEY_VAR)
        if not token:
            raise ModelUnavailable(f"{KEY_VAR} is not set. Set it (see README) or run with --offline to replay the cache.")
        url = ENDPOINT.format(region=os.environ.get(REGION_VAR, "us-east-1"))
        body = json.dumps(payload).encode()
        last = None
        for attempt in range(MAX_RETRIES):
            request = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {token}", "content-type": "application/json"})
            started = time.time()
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    data = json.loads(response.read())
                usage = data.get("usage") or {}
                self.ledger.add(model, role, calls=1, seconds=time.time() - started,
                                input_tokens=int(usage.get("prompt_tokens") or 0),
                                output_tokens=int(usage.get("completion_tokens") or 0))
                return data["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:200]!r}"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(2 ** attempt)
        self.ledger.add(model, role, failures=1)
        raise ModelUnavailable(f"{role} call to {model} failed: {last}")
