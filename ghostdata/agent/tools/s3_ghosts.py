from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...config import CACHE_DIR, ablated
from ...observations import USER_RE, identifier_keys

BUCKET_VAR = "GHOSTDATA_S3_BUCKET"
ROLE_VAR = "GHOSTDATA_ROLE_ARN"
RUN_VAR = "GHOSTDATA_RUN"
MAX_VERSIONS = 400
MAX_BYTES = 1_000_000
WINDOW = 160


class S3Unavailable(RuntimeError):
    pass


@dataclass
class GhostCopy:
    """One object version whose bytes carry one of the subject's identifiers."""

    bucket: str
    key: str
    version_id: str
    last_modified: str
    is_latest: bool
    hidden_by_delete_marker: bool
    legal_hold: bool
    matched: list
    window: str
    linked: list = field(default_factory=list)
    pii_types: list = field(default_factory=list)

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}?versionId={self.version_id}"

    @property
    def delete_command(self) -> str:
        return f"aws s3api delete-object --bucket {self.bucket} --key {self.key} --version-id {self.version_id}"


@dataclass
class Search:
    bucket: str
    prefix: str
    identifiers: list
    versions_seen: int = 0
    delete_markers: int = 0
    skipped: list = field(default_factory=list)
    truncated: bool = False
    copies: list = field(default_factory=list)
    request_ids: list = field(default_factory=list)

    def for_model(self) -> dict:
        return {
            "bucket": self.bucket, "prefix": self.prefix,
            "versions_scanned": self.versions_seen, "delete_markers": self.delete_markers,
            "truncated": f"stopped after {MAX_VERSIONS} versions; narrow the prefix" if self.truncated else "",
            "skipped": self.skipped[:10],
            "copies": [{"key": c.key, "version_id": c.version_id, "last_modified": c.last_modified,
                        "is_latest": c.is_latest, "hidden_by_delete_marker": c.hidden_by_delete_marker,
                        "legal_hold": c.legal_hold, "matched": c.matched, "linked_identifiers": c.linked,
                        "pii_types": c.pii_types}
                       for c in self.copies],
        }


def _window(text: str, needles: list[str]) -> str:
    low = text.lower()
    for n in needles:
        i = low.find(n.lower())
        if i >= 0:
            return text[max(0, i - WINDOW // 2): i + len(n) + WINDOW // 2]
    return text[:WINDOW]


HASH_IN_TEXT = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def text_keys(value) -> set[str]:
    """Identifiers in object bytes: the agent's own normaliser, plus email hashes written inside a line."""
    keys = identifier_keys(value)
    for s in value if isinstance(value, list) else [value]:
        if isinstance(s, str):
            keys |= {m.lower() for m in HASH_IN_TEXT.findall(s)}
    return keys


def _records(text: str) -> list:
    """The units an identifier can share with another: the scalar fields of each JSON object, else each line."""
    try:
        data = json.loads(text)
    except ValueError:
        return text.splitlines()
    out = []

    def walk(v):
        if isinstance(v, dict):
            out.append([x for x in v.values() if not isinstance(x, (dict, list))])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            out.append([x for x in v if not isinstance(x, (dict, list))])
            for x in v:
                walk(x)
    walk(data)
    return out or [text]


def linked_identifiers(text: str, identifiers: set[str]) -> list[str]:
    """Other identifiers written in the same record as one of the subject's."""
    out = set()
    for record in _records(text):
        keys = text_keys(record)
        if keys & identifiers:
            out |= keys - identifiers
    return sorted(k for k in out if not USER_RE.match(k))


def _surface(key: str) -> list[str]:
    """How a normalised identifier is written in the text, so a window can be cut around it."""
    if key.startswith("+"):
        digits = key[1:]
        return [digits[-7:], digits[-4:]]
    return [key]


class GhostFinder:
    """Lists every version and delete marker under a prefix and reads each version's bytes.
    Matching is the same identifier normalisation the rest of the agent uses for evidence files."""

    def __init__(self, bucket: str, session=None, comprehend: bool = True, region: str | None = None):
        self.bucket = bucket
        self._session = session
        self.comprehend = comprehend
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.calls = 0
        self._sessions: dict = {}

    def session(self, label: str = "ghostdata-agent"):
        if self._session is not None:
            return self._session
        if label not in self._sessions:
            self._sessions[label] = self._assume(label)
        return self._sessions[label]

    def _assume(self, label: str):
        try:
            import boto3
        except ImportError as e:
            raise S3Unavailable("boto3 is not installed; pip install boto3 to use the S3 tool") from e
        base = boto3.Session(region_name=self.region)
        role = os.environ.get(ROLE_VAR)
        if not role:
            return base
        cr = base.client("sts").assume_role(RoleArn=role, RoleSessionName=label[:64])["Credentials"]
        return boto3.Session(aws_access_key_id=cr["AccessKeyId"], aws_secret_access_key=cr["SecretAccessKey"],
                             aws_session_token=cr["SessionToken"], region_name=self.region)

    def prefixes(self, session, prefix: str = "") -> dict:
        s3 = session.client("s3")
        out: dict = {}
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=self.bucket, Prefix=prefix):
            self.calls += 1
            for row in page.get("Versions", []) + page.get("DeleteMarkers", []):
                rest = row["Key"][len(prefix):]
                top = prefix + rest.split("/", 1)[0] + ("/" if "/" in rest else "")
                stats = out.setdefault(top, {"versions": 0, "delete_markers": 0})
                stats["delete_markers" if "Size" not in row else "versions"] += 1
        return dict(sorted(out.items()))

    def search(self, session, prefix: str, identifiers: set[str]) -> Search:
        s3 = session.client("s3")
        found = Search(self.bucket, prefix, sorted(identifiers))
        versions, latest_marker = [], set()
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=self.bucket, Prefix=prefix):
            self.calls += 1
            found.request_ids.append(page["ResponseMetadata"].get("RequestId", ""))
            for m in page.get("DeleteMarkers", []):
                found.delete_markers += 1
                if m["IsLatest"]:
                    latest_marker.add(m["Key"])
            versions.extend(page.get("Versions", []))
        if len(versions) > MAX_VERSIONS:
            found.truncated = True
            versions = versions[:MAX_VERSIONS]
        for v in versions:
            found.versions_seen += 1
            if v["Size"] > MAX_BYTES:
                found.skipped.append(f"{v['Key']}?versionId={v['VersionId']}: {v['Size']} bytes, over the {MAX_BYTES} limit")
                continue
            try:
                body = s3.get_object(Bucket=self.bucket, Key=v["Key"], VersionId=v["VersionId"])
            except Exception as e:
                found.skipped.append(f"{v['Key']}?versionId={v['VersionId']}: {type(e).__name__}")
                continue
            self.calls += 1
            found.request_ids.append(body["ResponseMetadata"].get("RequestId", ""))
            text = body["Body"].read().decode("utf-8", errors="replace")
            hits = sorted(text_keys(text) & identifiers)
            if not hits:
                continue
            found.copies.append(GhostCopy(
                self.bucket, v["Key"], v["VersionId"], v["LastModified"].isoformat(), v["IsLatest"],
                v["Key"] in latest_marker, self._legal_hold(s3, v["Key"], v["VersionId"]), hits,
                _window(text, [s for h in hits for s in _surface(h)]), linked_identifiers(text, set(hits))))
        if self.comprehend and found.copies:
            self._label(session, found.copies)
        return found

    def _legal_hold(self, s3, key: str, version_id: str) -> bool:
        try:
            self.calls += 1
            hold = s3.get_object_legal_hold(Bucket=self.bucket, Key=key, VersionId=version_id)
            return hold["LegalHold"]["Status"] == "ON"
        except Exception:
            return False

    def _label(self, session, copies: list[GhostCopy]) -> None:
        client = session.client("comprehend")
        for c in copies:
            self.calls += 1
            try:
                entities = client.detect_pii_entities(Text=c.window[:4000], LanguageCode="en")["Entities"]
            except Exception as e:
                c.pii_types = [f"unlabelled: {type(e).__name__}"]
                continue
            c.pii_types = sorted({e["Type"] for e in entities if e["Score"] >= 0.5})


class RecordedFinder:
    """A live run always asks S3 and records the answer under the run label; an offline run replays it."""

    def __init__(self, finder: GhostFinder | None, offline: bool = False, cache_dir: Path = CACHE_DIR / "s3",
                 bucket: str = ""):
        self.finder = finder
        self.offline = offline
        self.cache_dir = cache_dir
        self.bucket = finder.bucket if finder else bucket
        self.run = os.environ.get(RUN_VAR, "default")

    def _path(self, op: str, *parts) -> Path:
        key = hashlib.sha256(json.dumps([op, self.run, self.bucket, *parts]).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _replay(self, path: Path, what: str):
        if not (self.offline or self.finder is None):
            return None
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise S3Unavailable(f"no recorded S3 answer for {what} in run {self.run!r}; run once with S3 access to record it")

    def _record(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")

    def prefixes(self, label: str, prefix: str = "") -> dict:
        path = self._path("prefixes", prefix)
        data = self._replay(path, f"prefixes under {prefix!r}")
        if data is None:
            data = self.finder.prefixes(self.finder.session(label), prefix)
            self._record(path, data)
        return data

    def search(self, label: str, prefix: str, identifiers: set[str]) -> Search:
        path = self._path("search", prefix, sorted(identifiers))
        data = self._replay(path, f"{prefix!r}")
        if data is None:
            data = asdict(self.finder.search(self.finder.session(label), prefix, identifiers))
            self._record(path, data)
        copies = [GhostCopy(**c) for c in data.pop("copies")]
        return Search(**data, copies=copies)


def configured(offline: bool = False) -> RecordedFinder | None:
    bucket = os.environ.get(BUCKET_VAR, "").strip()
    if not bucket or ablated("no_s3_tool"):
        return None
    return RecordedFinder(None if offline else GhostFinder(bucket), offline=offline, bucket=bucket)
