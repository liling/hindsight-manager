# Hindsight Manager
# Build context is the parent lab/ directory (set in docker-compose.yml),
# so both hindsight-manager/ and xinyi-platform/ sources are visible.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy xinyi-platform first (HM depends on it via pyproject.toml).
# Only copy runtime source — tests, .git, docs are excluded.
COPY xinyi-platform/pyproject.toml xinyi-platform/uv.lock /xinyi-platform/
COPY xinyi-platform/xinyi_platform /xinyi-platform/xinyi_platform/

# Copy HM manifests and sync deps.
COPY hindsight-manager/pyproject.toml hindsight-manager/uv.lock ./
RUN uv sync --frozen

COPY hindsight-manager/hindsight_manager ./hindsight_manager
RUN uv pip install -e .


FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -s /bin/bash hindsight

COPY --from=builder /app /app
COPY --from=builder /xinyi-platform /xinyi-platform

USER hindsight

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "hindsight_manager.main:app", "--host", "0.0.0.0", "--port", "8001"]
