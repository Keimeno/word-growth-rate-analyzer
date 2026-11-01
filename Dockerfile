# One image definition, three stages. Compose's `web` service builds the `web` target, the
# ingester and the analyzer the default (last) one; BuildKit only builds the stages a target
# needs, so the Node stage only runs for `web`.

# The dashboard's page: built once, served as static files by the Python API
FROM node:26-slim AS web-build
WORKDIR /web
# Node 25 and later no longer ship Corepack
RUN npm install -g pnpm@12.16.1
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# The web dashboard: the API and the built page on 3610
FROM base AS web
COPY --from=web-build /web/dist /app/web-dist
CMD ["wgra", "web", "--host", "0.0.0.0"]

# The ingester and the analyzer; config.yaml is mounted at runtime, see docker-compose.yml
FROM base AS app
CMD ["wgra", "ingest"]
