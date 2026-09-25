"""Exercise the T1 HTTP shell in an isolated new SQLite database."""

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/src"))

from kairos.api.schemas import ErrorResponse  # noqa: E402
from kairos.main import create_app  # noqa: E402


def main(openapi_file: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="kairos-contract-http-") as directory:
        with TestClient(create_app(str(Path(directory) / "runtime.sqlite3"))) as client:
            runtime_spec = client.get("/openapi.json")
            if runtime_spec.status_code != 200 or runtime_spec.json() != json.loads(openapi_file.read_text()):
                print("FAIL K15-HTTP: served OpenAPI differs from generated artifact")
                return 1
            health = client.get("/api/v1/health")
            if health.status_code != 200 or health.json() != {"status": "ok"}:
                print("FAIL K01-HTTP: new runtime health failed")
                return 1
            state = client.get("/api/v1/state")
            if state.status_code != 501:
                print("FAIL K15-HTTP: unimplemented state must return 501")
                return 1
            ErrorResponse.model_validate(state.json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
