from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = Path(os.environ.get("GHOST_DATASET", REPO_ROOT / "dataset")).resolve()


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class Request:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str
    reported_at: datetime
    audit_at: datetime
    request_text: str


def load_requests(path: Path) -> list[Request]:
    requests = [
        Request(
            case_id=r["case_id"],
            email=r["email"],
            requested_at=parse_time(r["requested_at"]),
            reported_status=r["reported_status"],
            reported_at=parse_time(r["reported_at"]),
            audit_at=parse_time(r["audit_at"]),
            request_text=r["request_text"],
        )
        for r in read_csv(path)
    ]
    return requests


def evidence_times(dataset_dir: Path = DATASET_DIR) -> dict[str, datetime]:
    """Time at which each citable evidence id came into existence."""
    times = {}
    for r in read_csv(dataset_dir / "evidence_files.csv"):
        times[r["file_id"]] = parse_time(r["captured_at"])
    for r in read_csv(dataset_dir / "system_activity.csv"):
        times[r["activity_id"]] = parse_time(r["event_time"])
    for r in read_csv(dataset_dir / "user_audit_log.csv"):
        times[r["audit_id"]] = parse_time(r["event_time"])
    return times
