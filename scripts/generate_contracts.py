"""Export deterministic transport artifacts from the new FastAPI application."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "services/api/src"


def generate(destination: Path) -> None:
    sys.path.insert(0, str(API_SRC))
    from kairos.main import create_app

    destination.mkdir(parents=True, exist_ok=True)
    openapi = destination / "openapi.json"
    openapi.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    generator = ROOT / "apps/web/node_modules/.bin/openapi-typescript"
    if not generator.is_file():
        raise RuntimeError("openapi-typescript missing; run npm ci in apps/web")
    subprocess.run([str(generator), str(openapi), "-o", str(destination / "backend-api.d.ts")], check=True)


if __name__ == "__main__":
    target = ROOT / "contracts" if len(sys.argv) == 1 else Path(sys.argv[1])
    generate(target)
