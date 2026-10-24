from __future__ import annotations

import re
from dataclasses import dataclass

NEGATIVE = [
    r"not (asking|a request) (for|to) (deletion|delete|erase)",
    r"\b(don'?t|do not) (delete|close|remove|erase)",
    r"without (removing|deleting)",
    r"\bleave (the|my) (account|profile)",
    r"\bkeep the account",
    r"\b(continue|still) (using|use|want|need)",
    r"marketing lists only",
]
POSITIVE = [
    r"\b(delet(e|ed|ing|ion)|eras(e|ed|ing|ure)|remov(e|ed|ing)|clos(e|ed|ing)|gone)\b",
    r"eliminar|eliminación|exclusão|suppression|supprimer|삭제|削除",
]


@dataclass(frozen=True)
class Intent:
    authorizes_deletion: bool
    reason: str
    source: str


def rule_intent(text: str) -> Intent:
    """Keyword baseline: a refusal phrase wins over a deletion word."""
    lowered = text.lower()
    for pattern in NEGATIVE:
        m = re.search(pattern, lowered)
        if m:
            return Intent(False, f'says "{m.group(0)}"', "rules")
    for pattern in POSITIVE:
        m = re.search(pattern, lowered)
        if m:
            return Intent(True, f'says "{m.group(0)}"', "rules")
    return Intent(False, "no deletion wording found", "rules")
