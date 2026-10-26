from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules)",
    r"disregard (the |your )?(rules|instructions|policy)",
    r"\b(system|assistant|developer)\s*:",
    r"you are now",
    r"mark (this|the case|it) (as )?(complete|completed|done)",
    r"(skip|do not check|don't check) (the )?(backups?|replicas?|logs?|legal hold)",
    r"(override|bypass) (the )?(policy|retention|legal hold)",
    r"</?\s*(request|evidence|system)\s*>",
]


def injection_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [m.group(0) for p in INJECTION_PATTERNS for m in [re.search(p, lowered)] if m]


def fence(tag: str, text: str) -> str:
    """Wrap untrusted text so a closing tag inside it cannot end the block."""
    safe = re.sub(r"</?\s*" + tag + r"\s*>", "[tag removed]", text, flags=re.I)
    return f"<{tag}>\n{safe}\n</{tag}>"
