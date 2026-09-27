import ast
from pathlib import Path


def find_forbidden_edges(source_root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        parts = relative.parts
        layer = parts[0] if parts else ""
        if layer not in {"domain", "application", "adapters", "api"}:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        for imported in imports:
            if layer == "domain" and (
                imported.startswith("kairos.")
                or imported.split(".", 1)[0] in {"fastapi", "pydantic"}
            ):
                violations.append(f"{relative}: domain cannot import {imported}")
            elif layer == "application" and imported.startswith(("kairos.adapters", "kairos.api")):
                violations.append(f"{relative}: application cannot import {imported}")
            elif layer == "adapters" and imported.startswith("kairos.api"):
                violations.append(f"{relative}: adapters cannot import {imported}")
            elif layer == "api" and imported.startswith(
                ("kairos.adapters", "kairos.domain", "kairos.settings")
            ):
                violations.append(f"{relative}: api cannot import {imported}")

    return violations


def test_project_layers_have_no_forbidden_imports() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "kairos"

    assert find_forbidden_edges(source_root) == []


def test_architecture_checker_finds_forbidden_import(tmp_path: Path) -> None:
    source_root = tmp_path / "kairos"
    application = source_root / "application"
    application.mkdir(parents=True)
    (application / "service.py").write_text(
        "from kairos.adapters.sqlite import Repository\n", encoding="utf-8"
    )

    violations = find_forbidden_edges(source_root)

    assert violations == [
        "application/service.py: application cannot import kairos.adapters.sqlite"
    ]
