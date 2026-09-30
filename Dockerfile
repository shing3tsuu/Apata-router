FROM python:3.14.5-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app


FROM base AS dependencies

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM dependencies AS development

RUN uv sync --frozen --group dev --no-install-project
COPY . .

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "--frozen", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM dependencies AS production

COPY alembic ./alembic
COPY alembic.ini ./
COPY src ./src

EXPOSE 8000

CMD ["uv", "run", "--frozen", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
