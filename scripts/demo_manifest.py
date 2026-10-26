from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cli"))

opened: set[Path] = set()


def hook(event: str, args: tuple) -> None:
    if event == "open" and isinstance(args[0], (str, Path)):
        p = Path(args[0]).resolve()
        if CACHE in p.parents and p.is_file():
            opened.add(p)


def main() -> int:
    """Replays every recorded demo run and lists exactly the cache files it read, so the public copy ships only those."""
    import demo
    sys.addaudithook(hook)
    runs = [r for r in sys.argv[1:]] or ["find", "find --no-model", "prove --after-fix"]
    for run in runs:
        words = run.split()
        if not (ROOT / "demo" / "results" / f"{words[0]}{'-no-model' if '--no-model' in words else ''}.json").exists():
            continue
        demo.main(["--recorded", "--run", *words])
    files = sorted(str(p.relative_to(ROOT)) for p in opened)
    out = ROOT / "demo" / "results" / "manifest.json"
    out.write_text(json.dumps({"cache_files": files}, indent=1) + "\n", encoding="utf-8")
    print(f"{len(files)} cache files read by the recorded demo; wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
