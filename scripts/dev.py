"""Start the two independently installed development services together."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "services/api/.venv/bin/python"
VITE = ROOT / "apps/web/node_modules/.bin/vite"


def main() -> int:
    if not PYTHON.exists() or not VITE.exists():
        print("Install services/api and apps/web dependencies first", file=sys.stderr)
        return 2
    db_directory = tempfile.TemporaryDirectory(prefix="kairos-dev-")
    env = {**os.environ, "KAIROS_DB_PATH": str(Path(db_directory.name) / "kairos.sqlite3")}
    api = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "kairos.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT / "services/api", env=env)
    web = subprocess.Popen([str(VITE), "--host", "127.0.0.1"], cwd=ROOT / "apps/web")
    try:
        while True:
            if api.poll() is not None:
                return api.returncode or 1
            if web.poll() is not None:
                return web.returncode or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        api.terminate()
        web.terminate()
        api.wait(timeout=5)
        web.wait(timeout=5)
        db_directory.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
