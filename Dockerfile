FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.12
COPY pyproject.toml uv.lock ./

FROM base AS runtime
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY services ./services
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 forget_lah
ENV PATH="/app/.venv/bin:$PATH"
USER forget_lah
CMD ["uvicorn", "forget_lah.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]

FROM base AS test
RUN uv sync --frozen --no-install-project
COPY src ./src
COPY services ./services
COPY migrations ./migrations
COPY tests ./tests
COPY alembic.ini ./
RUN uv sync --frozen && useradd --create-home --uid 10001 forget_lah && chown -R forget_lah /app
ENV PATH="/app/.venv/bin:$PATH"
USER forget_lah
CMD ["pytest", "-q"]
