"""Deterministic rebuild checks. Exit nonzero for failure or unavailable gates."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
LEGACY = ("XiAnHacker-view-v1", "XiAnHacker-backend-v1")
SKIP_DIRS = {"node_modules", ".venv", ".venv-py314", "dist", "__pycache__", ".pytest_cache", "var"}


def issue(rule: str, source: Path, detail: str, remedy: str) -> str:
    return f"FAIL {rule}: {source}: {detail}; fix: {remedy}"


def source_files(root: Path):
    for area in (root / "apps/web", root / "services/api"):
        if not area.exists():
            continue
        for directory, children, files in os.walk(area):
            children[:] = [child for child in children if child not in SKIP_DIRS]
            for name in files:
                path = Path(directory) / name
                if path.suffix in {".py", ".ts", ".tsx", ".vue", ".js", ".json", ".toml"}:
                    yield path


def python_imports(tree: ast.AST, source: Path, root: Path) -> list[str]:
    """Resolve absolute and relative Python import statements to package names."""
    package_root = root / "services/api/src"
    try:
        parts = list(source.relative_to(package_root).with_suffix("").parts)
    except ValueError:
        return []
    is_package_init = bool(parts and parts[-1] == "__init__")
    if is_package_init:
        parts.pop()
    package_parts = parts if is_package_init else parts[:-1]
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                # level=1 stays in this package, level=2 ascends one package.
                anchor_length = max(0, len(package_parts) - (node.level - 1))
                anchor = package_parts[:anchor_length]
                base = ".".join((*anchor, *((node.module or "").split(".") if node.module else ())))
            imports.append(base)
            imports.extend(f"{base}.{alias.name}" for alias in node.names if base)
    return imports


def legacy_inventory(root: Path) -> dict[str, str]:
    inventory = {}
    for name in LEGACY:
        area = root / name
        if not area.exists():
            continue
        for directory, children, files in os.walk(area, followlinks=False):
            children[:] = [child for child in children if child != ".git"]
            for filename in files:
                if filename == ".git":
                    continue
                path = Path(directory) / filename
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    inventory[relative] = "link:" + os.readlink(path)
                else:
                    inventory[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return inventory


def architecture(root: Path) -> list[str]:
    errors = []
    package = root / "apps/web/package.json"
    if package.exists():
        manifest = json.loads(package.read_text())
        dependencies = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
        for dependency, version in dependencies.items():
            if isinstance(version, str) and version.startswith(("file:", "link:", "workspace:", "../", "../../")):
                errors.append(issue("K01-INSTALL", package, f"{dependency} -> {version}", "use a declared registry dependency owned by apps/web"))
        if manifest.get("workspaces"):
            errors.append(issue("K01-INSTALL", package, "workspace dependency is not isolated", "keep apps/web independently installable"))
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = path.resolve()
            if any(name in target.parts for name in LEGACY):
                errors.append(issue("K01-LINK", path, f"symlink reaches {target}", "copy only reviewed new code"))
        content = path.read_text(errors="replace")
        if any(name in content for name in LEGACY):
            errors.append(issue("K01-RUNTIME", path, "runtime/config references a legacy tree", "remove the legacy path and use new package boundaries"))
        if path.suffix == ".py":
            try:
                tree = ast.parse(content, filename=relative)
            except SyntaxError as exc:
                errors.append(issue("ARCH-PARSE", path, str(exc), "repair Python syntax"))
                continue
            imports = python_imports(tree, path, root)
            if "/domain/" in relative:
                forbidden = ("fastapi", "starlette", "sqlalchemy", "sqlite3", "httpx", "requests", "uvicorn", "kairos.adapters", "kairos.api", "kairos.application")
                for item in imports:
                    if item.startswith(forbidden):
                        errors.append(issue("ARCH-DOMAIN", path, f"domain -> {item}", "depend on pure domain types only"))
            if "/application/" in relative:
                for item in imports:
                    if item.startswith(("kairos.adapters", "sqlite3", "fastapi", "httpx", "requests")):
                        errors.append(issue("ARCH-APPLICATION", path, f"application -> {item}", "inject a port from the composition root"))
            for item in imports:
                if item.startswith("kairos."):
                    target = root / "services/api/src" / (item.replace(".", "/") + ".py")
                    if not target.exists():
                        target = root / "services/api/src" / item.replace(".", "/") / "__init__.py"
                    if target.exists():
                        target_relative = target.relative_to(root).as_posix()
                        try:
                            target_layer = target.relative_to(root / "services/api/src/kairos").parts[0]
                        except (ValueError, IndexError):
                            target_layer = ""
                        if "/domain/" in relative and target_layer in {"api", "application", "adapters"}:
                            errors.append(issue("ARCH-EDGE", path, f"{relative} -> {target_relative}", "invert this dependency through a domain-owned interface"))
                        if "/application/" in relative and target_layer == "adapters":
                            errors.append(issue("ARCH-EDGE", path, f"{relative} -> {target_relative}", "inject the adapter at the composition root"))
        if relative.startswith("apps/web/src/") and path.suffix in {".ts", ".tsx", ".vue"}:
            if re.search(r"from\s*['\"][^'\"]*(services/api|XiAnHacker)", content):
                errors.append(issue("ARCH-WEB", path, "web import reaches server or legacy source", "use the generated contract and HTTP adapter"))
            if any(f"/{layer}/" in relative for layer in ("scene", "presentation", "assistant")) and "fetch(" in content:
                errors.append(issue("ARCH-WEB", path, "view layer performs HTTP", "inject data through an API port"))
            for specifier in re.findall(r"(?:import|export)\s+(?:[^'\"]+\s+from\s+)?['\"]([^'\"]+)['\"]", content):
                if specifier.startswith("."):
                    target = (path.parent / specifier).resolve()
                    if any(name in target.parts for name in LEGACY):
                        errors.append(issue("K01-EDGE", path, f"{relative} -> {target}", "import new code or the generated contract"))
                    if "/scene/" in relative and "/api/" in target.as_posix():
                        errors.append(issue("ARCH-SCENE", path, f"scene -> {target}", "inject already mapped environment data"))
    baseline = PROJECT / "scripts/legacy-baseline.json"
    if root == PROJECT and baseline.exists():
        expected = json.loads(baseline.read_text())
        actual = legacy_inventory(root)
        for name in sorted(set(expected) | set(actual)):
            if name in actual and name in expected and expected[name] == actual[name]:
                continue
            # A checkout may omit both old trees; it remains an isolated new build.
            if not any((root / legacy).exists() for legacy in LEGACY):
                break
            errors.append(issue("K01-FREEZE", root / name, "legacy content differs from frozen baseline", "restore or review the source change without using it at runtime"))
    return errors


def production_bundle(root: Path) -> list[str]:
    errors = []
    dist = root / "apps/web/dist"
    if not dist.exists():
        return ["BLOCKED K01-BUNDLE: web production bundle missing; run the web build"]
    for path in dist.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink() and any(name in path.resolve().parts for name in LEGACY):
            errors.append(issue("K01-BUNDLE", path, "bundle link reaches legacy tree", "build only from new source"))
        if path.suffix in {".js", ".css", ".html", ".map"}:
            content = path.read_text(errors="replace")
            if any(name in content for name in LEGACY) or "architecture_bad" in content or "synthetic_only" in content:
                errors.append(issue("K01-BUNDLE", path, "legacy or test fixture reference in production output", "remove fixture or legacy import from the build graph"))
    return errors


def docs(root: Path) -> list[str]:
    errors = []
    required = (
        "AGENTS.md", "ARCHITECTURE.md", "README.md", "docs/PRODUCT_MEMORY.md",
        "docs/design/FRONTEND_SPEC.md", "docs/design/STATE_MODEL.md",
        "docs/design/BACKEND_REUSE.md", "docs/engineering/HARNESS.md",
    )
    for name in required:
        if not (root / name).exists():
            errors.append(issue("DOC-SOURCE", root / name, "authoritative document missing", "include the reviewed planning document in this checkout"))
    documents = [root / name for name in ("AGENTS.md", "ARCHITECTURE.md", "README.md")]
    documents = [path for path in documents if path.exists()]
    documents += list((root / "docs").rglob("*.md")) if (root / "docs").exists() else []
    for path in documents:
        content = path.read_text()
        if path.as_posix().endswith(("ARCHITECTURE.md", "FRONTEND_SPEC.md", "STATE_MODEL.md", "BACKEND_REUSE.md", "HARNESS.md")) and "状态：" not in content[:500]:
            errors.append(issue("DOC-STATUS", path, "decision/implementation status marker missing", "state whether this is a proposal or implemented evidence"))
        for referenced in re.findall(r"\bK(\d{2})\b", content):
            if not 1 <= int(referenced) <= 16:
                errors.append(issue("DOC-REQ", path, f"unknown K{referenced}", "use an ID from HARNESS.md"))
        # Strip fenced examples, then check local Markdown targets.
        content = re.sub(r"```.*?```", "", content, flags=re.S)
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", content):
            target = target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            if not (path.parent / target).exists():
                errors.append(issue("DOC-LINK", path, f"missing {target}", "correct the relative link or add its target"))
    harness = (root / "docs/engineering/HARNESS.md")
    if harness.exists():
        content = harness.read_text()
        for number in range(1, 17):
            if f"| K{number:02d} |" not in content:
                errors.append(issue("DOC-REQ", harness, f"K{number:02d} missing", "restore the requirement index"))
    return errors


def contracts(root: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="kairos-contracts-") as directory:
        env = {**os.environ, "PYTHONPATH": str(root / "services/api/src")}
        first = Path(directory) / "first"
        second = Path(directory) / "second"
        command = [str(root / "services/api/.venv/bin/python"), str(root / "scripts/generate_contracts.py"), str(first)]
        if not Path(command[0]).exists():
            return ["BLOCKED contracts: API venv missing; install services/api dependencies"]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        if result.returncode:
            return [f"BLOCKED contracts: generation exited {result.returncode}: {result.stderr.strip()}"]
        command[-1] = str(second)
        repeat = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        if repeat.returncode:
            return [f"BLOCKED contracts: second generation exited {repeat.returncode}: {repeat.stderr.strip()}"]
        errors = []
        for filename in ("openapi.json", "backend-api.d.ts"):
            generated = (first / filename).read_bytes()
            committed = root / "contracts" / filename
            if generated != (second / filename).read_bytes():
                errors.append(issue("K15-DETERMINISM", first / filename, "two generations differ", "remove nondeterministic metadata or ordering"))
            if not committed.exists() or committed.read_bytes() != generated:
                errors.append(issue("K15-GENERATION", committed, "generated artifact differs", "run scripts/generate_contracts.py and review the diff"))
        if errors:
            return errors
        smoke = subprocess.run([str(root / "services/api/.venv/bin/python"), str(root / "scripts/verify_contract_http.py"), str(first / "openapi.json")], cwd=root, capture_output=True, text=True)
        if smoke.returncode:
            errors.append(issue("K15-HTTP", root / "services/api/src/kairos/main.py", smoke.stdout.strip() or smoke.stderr.strip(), "align the running app with its generated contract"))
        return errors


def command_check(command: list[str], cwd: Path) -> list[str]:
    executable = Path(command[0])
    found = executable if executable.is_absolute() or executable.parent != Path(".") else Path(shutil.which(command[0]) or "")
    if not found.exists():
        return [f"BLOCKED {' '.join(command)}: executable missing"]
    result = subprocess.run(command, cwd=cwd)
    return [] if result.returncode == 0 else [f"FAIL {' '.join(command)}: exit {result.returncode}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=("docs", "architecture", "contracts", "api", "web", "e2e", "all"))
    parser.add_argument("--root", type=Path, default=PROJECT, help="test-only alternate root for architecture fixture")
    args = parser.parse_args()
    root = args.root.resolve()
    scopes = ("docs", "architecture", "contracts", "api", "web", "e2e") if args.scope == "all" else (args.scope,)
    errors = []
    for scope in scopes:
        if scope == "docs":
            errors += docs(root)
        elif scope == "architecture":
            errors += architecture(root)
            if root == PROJECT and (root / "apps/web/package.json").exists():
                errors += command_check([str(root / "apps/web/node_modules/.bin/vite"), "build"], root / "apps/web")
                if not errors:
                    errors += production_bundle(root)
        elif scope == "contracts":
            errors += contracts(root)
        elif scope == "api":
            errors += command_check([str(root / "services/api/.venv/bin/python"), "-m", "pytest", "-q", "services/api/tests", "tests/test_t1.py"], root)
        elif scope == "web":
            errors += command_check(["npm", "test", "--prefix", str(root / "apps/web")], root)
            errors += command_check([str(root / "apps/web/node_modules/.bin/vue-tsc"), "--noEmit"], root / "apps/web")
            errors += command_check([str(root / "apps/web/node_modules/.bin/vite"), "build"], root / "apps/web")
        else:
            errors.append("NOT_RUN e2e: T1 has no browser journey; K02-K16 browser evidence belongs to T10")
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f"PASS {args.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
