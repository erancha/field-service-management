import shutil
import subprocess
import sys
from pathlib import Path


def test_import_contracts_hold():
    # Locate the lint-imports console script from the active venv; fall back to
    # an absolute path derived from sys.executable when shutil.which misses it
    # (e.g. if the test runner has a narrowed PATH).
    lint_imports = shutil.which("lint-imports")
    if lint_imports is None:
        lint_imports = str(Path(sys.executable).parent / "lint-imports")

    if lint_imports is None or not Path(lint_imports).is_file():
        raise RuntimeError(
            "lint-imports console script not found; install dev dependencies with "
            "`pip install -e \".[dev]\"` so the import boundary guard can run."
        )

    # import-linter reads [tool.importlinter] from pyproject.toml; it must run
    # with backend/ as the working directory so it finds that file.
    backend_dir = Path(__file__).parent.parent

    result = subprocess.run(
        [lint_imports],
        capture_output=True,
        text=True,
        cwd=backend_dir,
    )
    assert result.returncode == 0, result.stdout + result.stderr
