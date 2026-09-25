import subprocess
import sys
from pathlib import Path


def test_documentation_checker_reports_missing_local_link(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("[missing](docs/not-created.md)\n", encoding="utf-8")
    checker = Path(__file__).resolve().parents[2] / "scripts" / "check_docs.py"

    result = subprocess.run(
        [sys.executable, str(checker), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "README.md: docs/not-created.md" in result.stderr
