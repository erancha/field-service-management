# Tools

Hands-on tools, run from any directory against the Compose stack; `--ec2` as the first argument
acts on the stack's EC2 instance. Each prints its full usage with `--help`.

- `sql-helper.sh [--ec2]` — psql on the stack's database: a shell, `-c`, a SQL file, row counts
  and rows of every table, and `--backup <file>` / `--restore <file>` of the whole database.
- `lock.sh` — recompiles `backend/requirements.txt` inside the Dockerfile's Python image; run it
  after editing the dependency list.
- `release.sh [--minor|--major]` — tags the next version and pushes the tag, which the CI
  workflow publishes as a GitHub Release once the tests pass.

Back to the [README](../../README.md).
