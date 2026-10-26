from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MAX_USD = 2.00
DEFAULT_MAX_CALLS = 5000
DEFAULT_MAX_TOKENS = 5_000_000


@dataclass(frozen=True)
class SpendCaps:
    """Per-run ceilings on live model calls. Cache replays cost nothing and never count."""

    usd: float = DEFAULT_MAX_USD
    calls: int = DEFAULT_MAX_CALLS
    tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls) -> "SpendCaps":
        return cls(usd=float(os.environ.get("GHOST_MAX_USD") or DEFAULT_MAX_USD),
                   calls=int(os.environ.get("GHOST_MAX_CALLS") or DEFAULT_MAX_CALLS),
                   tokens=int(os.environ.get("GHOST_MAX_TOKENS") or DEFAULT_MAX_TOKENS))

    def describe(self) -> str:
        return f"${self.usd:.2f} / {self.calls:,} calls / {self.tokens:,} tokens"
