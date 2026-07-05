# Project instructions

## Architecture comes first

Before writing, moving, or importing any backend code, read the **Architecture** section of
`README.md` — in particular its **Import rules** table. Every allowed dependency direction is
listed there; anything else is a violation, even if Python happily imports it.

The rules are executable: import-linter contracts in `backend/pyproject.toml`
(`[tool.importlinter]`) enforce them, and CI fails on any violating import. After adding or
relocating modules or imports, run:

```bash
cd backend && .venv/bin/lint-imports
```

Design changes that need a new cross-package dependency are architecture decisions, not local
edits: propose them explicitly (including the contract change) rather than working around a
contract with re-exports, lazy imports, or copies.
