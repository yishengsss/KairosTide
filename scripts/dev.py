"""Start the two independently installed development services together."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "services/api/.venv/bin/python"
VITE = ROOT / "apps/web/node_modules/.bin/vite"


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without shell expansion or logging values."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}; expected KEY=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid .env variable name on line {line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def main() -> int:
    if not PYTHON.exists() or not VITE.exists():
        print("Install services/api and apps/web dependencies first", file=sys.stderr)
        return 2
    api_environment = os.environ.copy()
    try:
        for name, value in read_dotenv(ROOT / ".env").items():
            api_environment.setdefault(name, value)
    except (OSError, ValueError) as error:
        print(f"Could not read project .env: {error}", file=sys.stderr)
        return 2

    key_file = api_environment.get("MIMO_API_KEY_FILE", "").strip()
    if key_file and not api_environment.get("MIMO_API_KEY", "").strip():
        try:
            api_key = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            print("Could not read the configured MiMo key file", file=sys.stderr)
            return 2
        if not api_key:
            print("The configured MiMo key file is empty", file=sys.stderr)
            return 2
        api_environment["MIMO_API_KEY"] = api_key
    api_environment.pop("MIMO_API_KEY_FILE", None)

    web_environment = {
        key: value for key, value in os.environ.items()
        if key not in {"MIMO_API_KEY", "MIMO_API_KEY_FILE"}
    }
    api_environment.setdefault("KAIROS_DB_PATH", str(ROOT / "var" / "kairos-dev.sqlite3"))
    api = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "kairos.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT / "services/api", env=api_environment)
    web = subprocess.Popen([str(VITE), "--host", "127.0.0.1"], cwd=ROOT / "apps/web", env=web_environment)
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


if __name__ == "__main__":
    raise SystemExit(main())
