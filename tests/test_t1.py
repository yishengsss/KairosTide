"""T1 boundary and empty-runtime contract checks."""

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BoundaryTests(unittest.TestCase):
    def test_synthetic_legacy_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "tests/fixtures/architecture_bad/services", root / "services")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check.py"), "architecture", "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("K01", result.stdout + result.stderr)
            self.assertIn("bad.py", result.stdout + result.stderr)

    def test_synthetic_direction_violation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "tests/fixtures/architecture_bad/services", root / "services")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check.py"), "architecture", "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ARCH-DOMAIN", result.stdout + result.stderr)


class ContractTests(unittest.TestCase):
    def test_openapi_exposes_required_transport_groups(self):
        document = json.loads((ROOT / "contracts/openapi.json").read_text())
        paths = document["paths"]
        for path in (
            "/api/v1/state", "/api/v1/drafts", "/api/v1/conflict-decisions",
            "/api/v1/flexible-tasks", "/api/v1/conversations", "/api/v1/weather",
        ):
            self.assertIn(path, paths)
        self.assertIn("DraftResponse", document["components"]["schemas"])
        operation = paths["/api/v1/drafts"]["post"]
        self.assertEqual(
            operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ErrorResponse",
        )

    def test_relative_import_crossing_domain_boundary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "tests/fixtures/architecture_bad/services", root / "services")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check.py"), "architecture", "--root", str(root)],
                capture_output=True,
                text=True,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ARCH-DOMAIN", output)
            self.assertIn("kairos.api", output)

    def test_relative_import_within_domain_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "services/api/src/kairos/domain"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (package / "events.py").write_text("from . import time_rules\n")
            (package / "time_rules.py").write_text("def valid():\n    return True\n")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check.py"), "architecture", "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_command_resolves_executables_from_path(self):
        spec = importlib.util.spec_from_file_location("kairos_check", ROOT / "scripts/check.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        self.assertEqual(checker.command_check(["python3", "-c", "pass"], ROOT), [])

    def test_invalid_request_uses_unified_error_contract(self):
        from fastapi.testclient import TestClient
        from kairos.main import create_app

        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(str(Path(directory) / "api.sqlite3"))).post(
                "/api/v1/drafts", json={}, headers={"Idempotency-Key": "bad-request"}
            )
        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["code"], "VALIDATION_ERROR")
        self.assertTrue(payload["request_id"])
        self.assertIn("field_errors", payload)
        self.assertNotIn("detail", payload)

    def test_deadline_schema_preserves_date_or_instant_precision(self):
        from datetime import date, datetime

        sys.path.insert(0, str(ROOT / "services/api/src"))
        from kairos.api.schemas import FlexibleTaskRequest

        base = {"title": "test", "timezone": "Asia/Shanghai", "source_message_id": "m1"}
        day = FlexibleTaskRequest.model_validate({**base, "deadline": "2026-10-02", "deadline_precision": "date"})
        instant = FlexibleTaskRequest.model_validate({**base, "deadline": "2026-10-02T14:30:00+08:00", "deadline_precision": "instant"})
        self.assertIsInstance(day.deadline, date)
        self.assertNotIsInstance(day.deadline, datetime)
        self.assertIsInstance(instant.deadline, datetime)
        with self.assertRaises(Exception):
            FlexibleTaskRequest.model_validate({**base, "deadline": "someday", "deadline_precision": "date"})


if __name__ == "__main__":
    unittest.main()
