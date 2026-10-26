from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "cache"
PROMPT_DIR = Path(__file__).resolve().parent / "agent" / "prompts"

PROVIDER = "Amazon Bedrock (OpenAI-compatible endpoint)"
ENDPOINT = "https://bedrock-mantle.{region}.api.aws/v1/chat/completions"
KEY_VAR = "AWS_BEARER_TOKEN_BEDROCK"
REGION_VAR = "AWS_REGION"

MODELS = {
    "intent": "qwen.qwen3-235b-a22b-2507",
    "vision": "qwen.qwen3-vl-235b-a22b-instruct",
    "investigator": "qwen.qwen3-235b-a22b-2507",
}

# USD per million tokens. Estimates from the Amazon Bedrock on-demand price list; the endpoint returns no price.
PRICES = {
    "qwen.qwen3-235b-a22b-2507": (0.22, 0.88),
    "qwen.qwen3-vl-235b-a22b-instruct": (0.53, 2.66),
    "qwen.qwen3-32b": (0.15, 0.60),
    "deepseek.v3.2": (0.62, 1.85),
    "moonshotai.kimi-k2.5": (0.60, 3.00),
}

TIMEOUT_SECONDS = 90
MAX_RETRIES = 4
INVESTIGATOR_MAX_ROUNDS = 6


def ablated(name: str) -> bool:
    """Ablations switch one mechanism off for measurement only (GHOST_ABLATE=name,name)."""
    return name in os.environ.get("GHOST_ABLATE", "").split(",")


def load_env(path: Path = REPO_ROOT / ".env") -> None:
    """Read KEY=VALUE lines from an uncommitted .env file without overriding the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
