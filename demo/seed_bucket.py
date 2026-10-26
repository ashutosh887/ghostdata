"""Seed the demo bucket with the S3 side of the synthetic world, then write demo/scenarios.json.

Run with a scoped profile, never root keys:
    AWS_PROFILE=unforged-agent python3 demo/seed_bucket.py --reset

boto3 is allowed here because this script only builds the demo; the audit itself stays standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_world import BUCKET, CUSTOMERS, DEMO_DIR, REGION, TOP, sha, s3_objects  # noqa: E402

BUCKET = os.environ.get("GHOSTDATA_S3_BUCKET", BUCKET)


def all_versions(s3, prefix: str) -> list[dict]:
    out = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=BUCKET, Prefix=prefix):
        for v in page.get("Versions", []):
            out.append({**v, "marker": False})
        for m in page.get("DeleteMarkers", []):
            out.append({**m, "marker": True})
    return out


def reset(s3) -> int:
    """Remove every version and delete marker under the demo prefix, lifting legal holds first."""
    found = all_versions(s3, TOP)
    for v in found:
        if v["marker"]:
            continue
        try:
            hold = s3.get_object_legal_hold(Bucket=BUCKET, Key=v["Key"], VersionId=v["VersionId"])["LegalHold"]["Status"]
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchObjectLockConfiguration", "InvalidRequest"):
                continue
            raise
        if hold == "ON":
            s3.put_object_legal_hold(Bucket=BUCKET, Key=v["Key"], VersionId=v["VersionId"], LegalHold={"Status": "OFF"})
    items = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in found]
    for i in range(0, len(items), 1000):
        result = s3.delete_objects(Bucket=BUCKET, Delete={"Objects": items[i:i + 1000], "Quiet": True})
        if result.get("Errors"):
            raise RuntimeError(f"reset failed: {result['Errors'][:3]}")
    return len(items)


def put(s3, key: str, body: bytes, hold: bool) -> str:
    extra = {"ObjectLockLegalHoldStatus": "ON"} if hold else {}
    content_type = "application/json" if key.endswith((".json", ".jsonl")) else "text/plain"
    if key.endswith(".csv"):
        content_type = "text/csv"
    return s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type, **extra)["VersionId"]


KIND = {"decoy": "email", "near_miss": "email", "email_and_linked": "email"}


def seed(s3) -> dict[str, list[dict]]:
    """Apply each object's plan and return what was planted, by case id."""
    planted: dict[str, list[dict]] = {}
    for c, o, bodies in s3_objects():
        hold = o.plan in ("hold", "hold_marker")
        versions = [put(s3, o.key, b, hold) for b in bodies]
        if o.plan in ("marker", "hold_marker"):
            s3.delete_object(Bucket=BUCKET, Key=o.key)
        elif o.plan == "purged":
            for v in versions:
                s3.delete_object(Bucket=BUCKET, Key=o.key, VersionId=v)
        planted.setdefault(c.case_id, []).append({"key": o.key, "version_id": versions[0],
                                                  "identifier_kind": KIND.get(o.ident, o.ident), "expected": o.expected})
    return planted


def identifiers(c) -> list[str]:
    emails = [c.email] + ([c.old_email] if c.old_email else [])
    return emails + [c.phone] + [sha(e) for e in emails]


def write_scenarios(planted: dict[str, list[dict]]) -> Path:
    cases = {}
    for c in CUSTOMERS:
        cases[c.case_id] = {
            "scenario": c.scenario,
            "group": c.group,
            "attack": c.attack or "",
            "expected_before": "COMPLETE" if c.deletion else "NOT_APPLICABLE",
            "expected_after": c.expected_after,
            "identifiers": identifiers(c),
            "planted": planted.get(c.case_id, []),
        }
    path = DEMO_DIR / "scenarios.json"
    doc = {"bucket": BUCKET, "prefix": TOP, "cases": cases}
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the S3 ghost-copy demo bucket")
    parser.add_argument("--reset", action="store_true", help="remove every demo version and marker first")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=REGION)
    existing = all_versions(s3, TOP)
    if existing and not args.reset:
        parser.error(f"{len(existing)} versions already under s3://{BUCKET}/{TOP}; rerun with --reset")
    if args.reset:
        print(f"reset: removed {reset(s3)} versions and delete markers under s3://{BUCKET}/{TOP}")

    planted = seed(s3)
    path = write_scenarios(planted)
    print(f"wrote {path}")

    listing = all_versions(s3, TOP)
    for v in sorted(listing, key=lambda v: (v["Key"], v["LastModified"])):
        kind = "delete-marker" if v["marker"] else f"version {v['Size']}B"
        print(f"{v['Key']}  {v['VersionId']}  {kind}{'  (latest)' if v['IsLatest'] else ''}")
    versions = sum(not v["marker"] for v in listing)
    print(f"{versions} versions, {len(listing) - versions} delete markers under s3://{BUCKET}/{TOP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
