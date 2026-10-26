from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from ..config import CACHE_DIR, ENDPOINT, KEY_VAR, MAX_RETRIES, MODELS, PROMPT_DIR, REGION_VAR, TIMEOUT_SECONDS, ablated
from ..dataset import Request
from ..identity import email_hash
from ..observations import identifier_keys
from .llm import CacheMiss, ModelClient, ModelOutage
from .tools.s3_ghosts import GhostCopy, RecordedFinder

MAX_ROUNDS = 8
SCOPE_VAR = "GHOSTDATA_S3_PREFIX"

TOOLS = [
    {"type": "function", "function": {
        "name": "list_prefixes",
        "description": "Top-level folders under a prefix in the bucket, with how many object versions and delete markers each holds. Delete markers hide older versions from a normal listing.",
        "parameters": {"type": "object", "properties": {
            "prefix": {"type": "string", "description": "Folder to list, ending in '/'; empty for the scope root."}},
            "required": ["prefix"]}}},
    {"type": "function", "function": {
        "name": "find_ghost_copies",
        "description": "Reads every version of every object under the prefix, including noncurrent versions hidden behind delete markers, and returns the versions whose bytes contain any of the given identifiers. Identifiers must be this subject's.",
        "parameters": {"type": "object", "properties": {
            "prefix": {"type": "string", "description": "Folder to search, ending in '/'."},
            "identifiers": {"type": "array", "items": {"type": "string"},
                            "description": "Emails (current and historical), phone numbers or sha256 email hashes of this subject."}},
            "required": ["prefix", "identifiers"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Stop searching. Call when every folder that could hold this subject's data has been searched with every identifier.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "One sentence: what was searched and what was found."}},
            "required": ["reason"]}}},
]


@dataclass
class Hunt:
    case_id: str
    calls: list = field(default_factory=list)
    refused: list = field(default_factory=list)
    copies: dict = field(default_factory=dict)
    by_model: set = field(default_factory=set)
    late: list = field(default_factory=list)
    searched: set = field(default_factory=set)
    sweeps: list = field(default_factory=list)
    derived: dict = field(default_factory=dict)
    request_ids: list = field(default_factory=list)
    outcome: str = ""
    error: str = ""

    @property
    def ghosts(self) -> list[GhostCopy]:
        return [c for _, c in sorted(self.copies.items())]


def _valid(arguments: str) -> str:
    """The endpoint rejects a history holding malformed arguments, so a cut-off call is echoed back as empty."""
    try:
        json.loads(arguments or "{}")
        return arguments or "{}"
    except json.JSONDecodeError:
        return "{}"


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ToolChat:
    """Native function calling on the Bedrock OpenAI-compatible endpoint, recorded for offline replay."""

    def __init__(self, client: ModelClient, cache_dir=CACHE_DIR / "tools"):
        self.client = client
        self.cache_dir = cache_dir

    def turn(self, role: str, model: str, messages: list, tools: list) -> dict:
        payload = {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto",
                   "max_tokens": 2000, "temperature": 0}
        key = _key(payload)
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists() and not self.client.fresh:
            self.client.ledger.add(model, role, cache_hits=1)
            return json.loads(path.read_text(encoding="utf-8"))["message"]
        if self.client.offline:
            raise CacheMiss(f"offline replay has no cached {role} turn ({key[:12]}); run online once to record it")
        self.client.check_caps(role)
        message = self._post(role, model, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"role": role, "model": model, "message": message}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return message

    def _post(self, role: str, model: str, payload: dict) -> dict:
        token = os.environ.get(KEY_VAR)
        if not token:
            raise ModelOutage(f"{KEY_VAR} is not set. Set it (see README) or run with --offline to replay the cache.")
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
                self.client.ledger.add(model, role, calls=1, seconds=time.time() - started,
                                       input_tokens=int(usage.get("prompt_tokens") or 0),
                                       output_tokens=int(usage.get("completion_tokens") or 0))
                message = data["choices"][0]["message"]
                return {"content": message.get("content") or "",
                        "tool_calls": [{"id": t["id"], "name": t["function"]["name"],
                                        "arguments": t["function"]["arguments"]} for t in message.get("tool_calls") or []]}
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:200]!r}"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(2 ** attempt)
        self.client.ledger.add(model, role, failures=1)
        raise ModelOutage(f"{role} call to {model} failed: {last}")


class GhostHunter:
    """The model chooses where to look and with which identifiers. Code runs every search, refuses identifiers
    that are not the subject's and repeated calls, and turns only byte-level matches into findings."""

    def __init__(self, auditor, client: ModelClient, finder: RecordedFinder, model: str = MODELS["investigator"]):
        self.auditor = auditor
        self.chat = ToolChat(client) if client is not None else None
        self.finder = finder
        self.model = model
        self.scope = os.environ.get(SCOPE_VAR, "")
        self.system = (PROMPT_DIR / "ghost_hunt.md").read_text(encoding="utf-8")

    def brief(self, r: Request, ident) -> str:
        current = self.current(ident)
        hashes = {email_hash(e): e for e in ident.emails}
        rows = []
        for k in sorted(ident.keys - {ident.user_id}):
            kind = "phone" if k.startswith("+") else "email" if "@" in k else "email_hash"
            row = {"identifier": k, "kind": kind, "current": k in current}
            if k in hashes:
                row["hash_of"] = hashes[k]
            rows.append(row)
        return json.dumps({"case_id": r.case_id, "audit_at": r.audit_at.isoformat(), "bucket": self.finder.bucket,
                           "scope_prefix": self.scope, "identifiers": rows})

    def current(self, ident) -> set:
        row = self.auditor.identities.users.get(ident.user_id, {})
        return identifier_keys([row.get("email", ""), row.get("phone", ""), row.get("email_hash", "")])

    def run(self, r: Request) -> Hunt:
        hunt = Hunt(r.case_id)
        ident = self.auditor.identities.resolve(r.email)
        if ident is None:
            return hunt
        subject = set(ident.keys) - {ident.user_id}
        label = f"ghostdata-{r.case_id}"
        seen = set()
        if self.chat is None:
            try:
                self.sweep(r, hunt, subject, label)
                hunt.outcome = "code sweep only (no model)"
            except Exception as e:
                hunt.error = f"s3 unavailable: {type(e).__name__}: {e}"
            return hunt
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": self.brief(r, ident)}]
        try:
            for _ in range(MAX_ROUNDS):
                message = self.chat.turn("ghost_hunt", self.model, messages, TOOLS)
                calls = message["tool_calls"]
                messages.append({"role": "assistant", "content": message["content"] or None,
                                 "tool_calls": [{"id": c["id"], "type": "function", "function": {
                                     "name": c["name"], "arguments": _valid(c["arguments"])}} for c in calls]} if calls
                                else {"role": "assistant", "content": message["content"]})
                if not calls:
                    hunt.outcome = "stopped without calling finish"
                    break
                done = False
                for c in calls:
                    result = self.execute(r, c, hunt, subject, seen, label)
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
                    done = done or c["name"] == "finish"
                if done:
                    break
            else:
                hunt.outcome = "stopped after the round limit"
            if not ablated("no_sweep"):
                self.sweep(r, hunt, subject, label)
        except CacheMiss:
            raise
        except ModelOutage as e:
            self.chat.client.fallback("ghost_hunt", r.case_id, e)
            hunt.outcome = f"model unavailable, code sweep only: {e}"
            try:
                self.sweep(r, hunt, subject, label)
            except Exception as s3:
                hunt.error = f"s3 unavailable: {type(s3).__name__}: {s3}"
        except Exception as e:
            hunt.error = f"s3 unavailable: {type(e).__name__}: {e}"
        return hunt

    def execute(self, r: Request, call: dict, hunt: Hunt, subject: set, seen: set, label: str) -> str:
        name = call["name"]
        try:
            args = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError:
            hunt.refused.append((name, call["arguments"][:200], "arguments are not JSON"))
            return "refused: the arguments were cut off or not valid JSON; call again with fewer identifiers per call"
        signature = json.dumps([name, args], sort_keys=True)
        hunt.calls.append((name, args))
        if name == "finish":
            hunt.outcome = f"finish: {args.get('reason', '')}"
            return "ok"
        if signature in seen:
            hunt.refused.append((name, args, "repeated call"))
            return "refused: this exact call already ran; its result is above"
        seen.add(signature)
        prefix = str(args.get("prefix", ""))
        if not prefix.startswith(self.scope):
            prefix = self.scope + prefix.lstrip("/")
        if name == "list_prefixes":
            return json.dumps({"prefix": prefix, "folders": self.finder.prefixes(label, prefix)}, sort_keys=True)
        if name != "find_ghost_copies":
            hunt.refused.append((name, args, "unknown tool"))
            return f"refused: no tool named {name!r}"
        asked = set()
        for value in args.get("identifiers") or []:
            asked |= identifier_keys(str(value)) or {str(value).strip().lower()}
        foreign = sorted(asked - subject - set(hunt.derived))
        if foreign:
            hunt.refused.append((name, foreign, "not this subject's identifiers"))
        wanted = asked & (subject | set(hunt.derived))
        if not wanted:
            return json.dumps({"refused": "none of these identifiers belong to this subject", "not_subject": foreign}, sort_keys=True)
        search = self.finder.search(label, prefix, wanted)
        hunt.searched |= {(prefix, k) for k in wanted}
        hunt.request_ids += search.request_ids
        for c in search.copies:
            if self.accept(r, c, hunt):
                hunt.by_model.add((c.key, c.version_id))
                self.derive(c, hunt, r)
        out = search.for_model()
        new = sorted(k for k in hunt.derived if (prefix, k) not in hunt.searched and k not in subject)
        if new:
            out["searchable_next"] = new
        if foreign:
            out["not_subject"] = foreign
        return json.dumps(out, sort_keys=True)

    def accept(self, r: Request, c: GhostCopy, hunt: Hunt) -> bool:
        """A version counts only if code read it, its bytes hold the subject's identifier, and it existed by audit_at."""
        if datetime.fromisoformat(c.last_modified) > r.audit_at:
            hunt.late.append(c.uri)
            return False
        hunt.copies.setdefault((c.key, c.version_id), c)
        return True

    def derive(self, c: GhostCopy, hunt: Hunt, r: Request) -> None:
        """An identifier written in the same record as a confirmed match may be searched next,
        unless the identity tables give it to someone else."""
        ident = self.auditor.identities.resolve(r.email)
        for k in c.linked:
            if k in ident.keys or self.auditor.identities.owners({k}) - {ident.user_id}:
                continue
            hunt.derived.setdefault(k, c.uri)

    def sweep(self, r: Request, hunt: Hunt, subject: set, label: str) -> None:
        """Code searches each folder with every identifier the model did not search it with,
        so a skipped folder never certifies COMPLETE and a folder the model covered is not read twice."""
        folders = list(self.finder.prefixes(label, self.scope)) or [self.scope]
        while True:
            gaps: dict = {}
            for k in subject | set(hunt.derived):
                for f in folders:
                    if not any(f.startswith(p) for p, searched in hunt.searched if searched == k):
                        gaps.setdefault(f, set()).add(k)
            if not gaps:
                return
            for f, keys in sorted(gaps.items()):
                search = self.finder.search(label, f, keys)
                hunt.sweeps.append((f, sorted(keys)))
                hunt.searched |= {(f, k) for k in keys}
                hunt.request_ids += search.request_ids
                for c in search.copies:
                    if self.accept(r, c, hunt):
                        self.derive(c, hunt, r)
