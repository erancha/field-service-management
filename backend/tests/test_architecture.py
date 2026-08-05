import shutil
import subprocess
import sys
from pathlib import Path


def test_no_foreign_keys_cross_context_boundaries():
    """Cross-context references are plain UUID columns, never database foreign keys
    (docs/data.md); a ForeignKey may only target a table declared in the same bounded
    context. This is the data-level counterpart of this file's import contracts.
    """
    import fsm.assist.adapters.orm  # noqa: F401
    import fsm.google_calendar.adapters.orm  # noqa: F401
    import fsm.identity.adapters.orm  # noqa: F401
    import fsm.notifications.adapters.orm  # noqa: F401
    import fsm.scheduling.adapters.orm  # noqa: F401
    from fsm.shared.db import Base

    # Table name -> bounded context, taken from the module that declared the mapped class
    # (fsm.<context>.adapters.orm).
    context_of_table = {
        mapper.local_table.name: mapper.class_.__module__.split(".")[1]
        for mapper in Base.registry.mappers
    }

    unmapped = set(Base.metadata.tables) - set(context_of_table)
    assert not unmapped, (
        f"Tables without a declaring context (defined outside the contexts' orm modules?): "
        f"{sorted(unmapped)}"
    )
    assert len(set(context_of_table.values())) >= 2, (
        "Expected tables from several contexts; the orm imports above no longer cover them."
    )

    violations = [
        f"{table.name}.{fk.parent.name} -> {fk.column.table.name} "
        f"({context_of_table[table.name]} -> {context_of_table[fk.column.table.name]})"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if context_of_table[fk.column.table.name] != context_of_table[table.name]
    ]
    assert not violations, (
        "Foreign keys crossing bounded-context boundaries (reference the other context "
        f"by plain UUID instead): {violations}"
    )


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
