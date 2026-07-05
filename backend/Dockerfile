FROM python:3.12-slim

WORKDIR /app

# Dependencies install pinned from the requirements.txt lockfile (compiled from pyproject.toml,
# regeneration command in its header), in their own layer so source edits reuse the cached
# dependency install. The package itself then installs with --no-deps so the version floors in
# pyproject.toml can never pull an unpinned dependency into the image. Alembic ships in the
# project dependencies, so the same image runs both migrations and the API.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8001 8002
