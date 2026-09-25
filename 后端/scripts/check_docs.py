from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def missing_links(root: Path) -> list[str]:
    missing: list[str] = []
    for document in sorted(root.rglob("*.md")):
        content = document.read_text(encoding="utf-8")
        for target in LINK_PATTERN.findall(content):
            target = target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            destination = (document.parent / unquote(target)).resolve()
            if not destination.exists():
                missing.append(f"{document.relative_to(root)}: {target}")
    return missing


def main(root: Path | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = (root or args.root).resolve()
    missing = missing_links(root)
    if missing:
        print("Broken local Markdown links:", file=sys.stderr)
        for link in missing:
            print(f"- {link}", file=sys.stderr)
        return 1
    print(f"Documentation links checked under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
