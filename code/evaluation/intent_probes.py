from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

from audit.agent.intent import ModelIntent  # noqa: E402
from audit.agent.llm import ModelClient  # noqa: E402
from audit.config import load_env  # noqa: E402
from audit.intent import rule_intent  # noqa: E402

PROBES = Path(__file__).resolve().parent / "intent_probes.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Score intent on hand-written phrasings outside the dataset")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--show", action="store_true", help="print every miss")
    args = parser.parse_args()
    load_env()
    model = ModelIntent(ModelClient(offline=args.offline))
    for split, probes in json.loads(PROBES.read_text(encoding="utf-8")).items():
        hits = {"model": 0, "keywords": 0}
        for p in probes:
            for name, fn in (("model", model), ("keywords", rule_intent)):
                got = fn(p["text"]).authorizes_deletion
                hits[name] += got == p["deletion"]
                if args.show and got != p["deletion"]:
                    print(f"  {split} {name} miss: {p['text']}")
        n = len(probes)
        print(f"{split}: n={n} model {hits['model']}/{n}, keywords {hits['keywords']}/{n}")


if __name__ == "__main__":
    main()
