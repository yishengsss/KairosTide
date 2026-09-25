"""T1 boundary and empty-runtime contract checks."""

import json
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


if __name__ == "__main__":
    unittest.main()
