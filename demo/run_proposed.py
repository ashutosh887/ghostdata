from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent
COMMAND = re.compile(r"^aws s3api delete-object .*$", re.M)


def proposed(report: Path) -> list[dict]:
    out = []
    for line in COMMAND.findall(report.read_text(encoding="utf-8")):
        words = shlex.split(line)
        args = {words[i][2:]: words[i + 1] for i in range(len(words) - 1) if words[i].startswith("--")}
        out.append({"Bucket": args["bucket"], "Key": args["key"], "VersionId": args["version-id"]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the delete commands an audit proposed. The agent never runs them; a person does, with their own credentials.")
    parser.add_argument("--report", type=Path, default=HERE / "results" / "find.md")
    parser.add_argument("--yes", action="store_true", help="actually delete; without it, only print")
    args = parser.parse_args()
    todo = proposed(args.report)
    s3 = boto3.client("s3")
    for item in todo:
        print(f"{'deleting' if args.yes else 'would delete'} s3://{item['Bucket']}/{item['Key']}?versionId={item['VersionId']}")
        if args.yes:
            s3.delete_object(**item)
    print(f"{len(todo)} versions {'deleted' if args.yes else 'listed; rerun with --yes to delete'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
