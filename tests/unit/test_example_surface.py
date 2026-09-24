
import ast
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = (
    PROJECT_ROOT / "examples" / "basic_orchestration" / "basic_orchestration.py",
    PROJECT_ROOT / "examples" / "local_study_room" / "local_study_room.py",
)

ALLOWED_PREFIXES = ("agent_squad", "agent_squad_aerospike", "ollama")


def _example_imports(example: Path) -> set[str]:
    tree = ast.parse(example.read_text(), filename=str(example))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_example_imports_only_public_packages(example: Path) -> None:
    unexpected = {
        module
        for module in _example_imports(example)
        if module not in sys.stdlib_module_names and not module.startswith(ALLOWED_PREFIXES)
    }
    assert not unexpected, f"{example.name} imports non-public modules: {unexpected}"


def test_wheel_import_without_source_tree(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to build the wheel")
    result = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"wheel build failed (offline?): {result.stderr.strip()}")
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1

    site = tmp_path / "site"
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel.extractall(site)

    saved_modules = dict(sys.modules)
    for name in [name for name in sys.modules if name.startswith("agent_squad_aerospike")]:
        del sys.modules[name]
    sys.path.insert(0, str(site))
    try:
        import agent_squad_aerospike

        resolved = Path(agent_squad_aerospike.__file__).resolve()
        assert str(site) in str(resolved)
        assert "src" not in resolved.parts
    finally:
        sys.path.remove(str(site))
        sys.modules.clear()
        sys.modules.update(saved_modules)
