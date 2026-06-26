FROM python:3.12-slim

WORKDIR /app

# Install the package and its runtime dependencies. Alembic ships in the project
# dependencies, so the same image runs both migrations and the API.
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

EXPOSE 8001 8002
