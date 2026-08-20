FROM ghcr.io/astral-sh/uv:0.5.11-python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY apps/api/src apps/api/src
COPY apps/api/migrations apps/api/migrations
COPY data/corpus/manifest.yaml data/corpus/manifest.yaml
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 10001 app
COPY --from=build --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH"
USER app
WORKDIR /app
EXPOSE 8000

CMD ["uvicorn", "compliance.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
