from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .dataset import Request
from .schema import OP_PHASE, OP_STATE, OUTPUT_HEADER, STATUSES, STEP_FIELDS, case_number, sort_key


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_steps(case_id: str, status: str, steps, audit_at: datetime | None,
                evidence_at: dict[str, datetime], report: Report) -> None:
    def err(msg: str) -> None:
        report.errors.append(f"{case_id}: {msg}")

    if not isinstance(steps, list):
        err("steps_json is not a JSON array")
        return
    if status == "NOT_APPLICABLE":
        if steps:
            err("NOT_APPLICABLE must have []")
        return
    if not steps:
        err(f"{status} has no steps")
        return

    prev = None
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != set(STEP_FIELDS):
            err(f"step {i} must have exactly the fields {', '.join(STEP_FIELDS)}")
            return
        if step["step_no"] != i:
            err(f"step {i} has step_no {step['step_no']}")
        op = step["operation"]
        if op not in OP_PHASE:
            err(f"step {i} has unknown operation {op}")
            return
        if step["phase"] != OP_PHASE[op] or step["state"] != OP_STATE[op]:
            err(f"step {i} pairs {op} with phase {step['phase']} and state {step['state']}")
            return
        for key in ("system_id", "resource_id", "evidence_id"):
            if not isinstance(step[key], str):
                err(f"step {i} {key} is not a string")
                return
        if not step["system_id"] or not step["resource_id"]:
            err(f"step {i} has an empty system_id or resource_id")
        key = sort_key(step["phase"], op, step["system_id"], step["resource_id"])
        if prev is not None and key < prev:
            err(f"step {i} breaks phase, operation, system_id, resource_id order")
        prev = key

        cited = step["evidence_id"]
        must_cite = step["phase"] == "FINDING" or status == "COMPLETE"
        if must_cite and not cited:
            err(f"step {i} ({op}) must cite evidence")
        if not must_cite and cited:
            err(f"step {i} ({op}) describes future work and must use an empty evidence_id")
        if cited:
            if cited not in evidence_at:
                err(f"step {i} cites unknown evidence {cited}")
            elif audit_at is not None and evidence_at[cited] > audit_at:
                err(f"step {i} cites {cited}, which postdates audit_at")

    phases = {s["phase"] for s in steps}
    if status == "COMPLETE" and phases != {"VERIFICATION"}:
        err("COMPLETE may contain only VERIFICATION steps")
    if status == "INCOMPLETE" and "FINDING" not in phases:
        err("INCOMPLETE must report at least one finding")
    if status == "INCOMPLETE" and "VERIFICATION" not in phases:
        err("INCOMPLETE must state the checks that pass after remediation")


def validate_output(path: Path, requests: list[Request], evidence_at: dict[str, datetime]) -> Report:
    report = Report()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = list(reader)
    if tuple(header or ()) != OUTPUT_HEADER:
        report.errors.append(f"header must be {','.join(OUTPUT_HEADER)}, got {header}")
        return report

    by_case = {r.case_id: r for r in requests}
    seen = []
    for row in rows:
        if len(row) != 3:
            report.errors.append(f"row {row[:1]} has {len(row)} columns")
            continue
        case_id, status, raw = row
        seen.append(case_id)
        if case_id not in by_case:
            report.errors.append(f"{case_id}: not in the request file")
            continue
        if status not in STATUSES:
            report.errors.append(f"{case_id}: unknown status {status}")
            continue
        try:
            steps = json.loads(raw)
        except json.JSONDecodeError as e:
            report.errors.append(f"{case_id}: steps_json is not valid JSON ({e})")
            continue
        check_steps(case_id, status, steps, by_case[case_id].audit_at, evidence_at, report)

    if len(seen) != len(set(seen)):
        report.errors.append("duplicate case_id rows")
    missing = set(by_case) - set(seen)
    if missing:
        report.errors.append(f"{len(missing)} requests have no row, e.g. {sorted(missing)[:3]}")
    if seen != sorted(seen, key=case_number):
        report.errors.append("rows are not sorted by case_id")
    return report
