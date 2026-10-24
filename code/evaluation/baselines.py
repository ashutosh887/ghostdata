from __future__ import annotations

from audit.dataset import Request


def trust_workflow(request: Request) -> tuple[str, str]:
    """Believe the deletion workflow's own claim."""
    return ("COMPLETE" if request.reported_status == "COMPLETE" else "INCOMPLETE"), "[]"


def always_incomplete(request: Request) -> tuple[str, str]:
    """Never certify a deletion."""
    return "INCOMPLETE", "[]"


BASELINES = {"trust_workflow": trust_workflow, "always_incomplete": always_incomplete}
