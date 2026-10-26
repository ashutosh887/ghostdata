from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent


def events(trail_bucket: str, account: str, region: str, since: datetime):
    s3 = boto3.client("s3")
    day = since.date()
    while day <= datetime.now(timezone.utc).date():
        prefix = f"AWSLogs/{account}/CloudTrail/{region}/{day:%Y/%m/%d}/"
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=trail_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < since:
                    continue
                body = gzip.decompress(s3.get_object(Bucket=trail_bucket, Key=obj["Key"])["Body"].read())
                yield from json.loads(body)["Records"]
        day += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the CloudTrail events the ghostdata-agent role made")
    parser.add_argument("--trail-bucket", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--hours", type=float, default=6)
    parser.add_argument("--since", help="ISO time; keep only events at or after it")
    parser.add_argument("--out", type=Path, default=HERE / "results" / "cloudtrail.json")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since) if args.since else datetime.now(timezone.utc) - timedelta(hours=args.hours)
    by_session = defaultdict(list)
    for e in events(args.trail_bucket, args.account, args.region, since):
        if datetime.fromisoformat(e["eventTime"].replace("Z", "+00:00")) < since:
            continue
        arn = e.get("userIdentity", {}).get("arn", "")
        if ":assumed-role/ghostdata-agent/" not in arn:
            continue
        params = e.get("requestParameters") or {}
        by_session[arn.rsplit("/", 1)[1]].append({
            "eventID": e["eventID"], "eventTime": e["eventTime"], "eventName": e["eventName"],
            "requestID": e.get("requestID", ""), "key": params.get("key", ""), "versionId": params.get("versionId", ""),
            "errorCode": e.get("errorCode", "")})
    out = {s: sorted(v, key=lambda x: x["eventTime"]) for s, v in sorted(by_session.items())}
    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    names = defaultdict(int)
    for rows in out.values():
        for row in rows:
            names[row["eventName"]] += 1
    print(f"{sum(names.values())} events from {len(out)} role sessions: {dict(names)}; wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
