# Hindsight Manager
# Build context is the parent lab/ directory (set in docker-compose.yml),
# so both hindsight-manager/ and xinyi-platform/ sources are visible.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy xinyi-platform first (HM depends on it via pyproject.toml)
COPY xinyi-platform /opt/xinyi-platform

# Copy HM manifests and sync deps.
# Both pyproject.toml and uv.lock contain the host-absolute path to xinyi-platform;
# rewrite both to /opt/xinyi-platform for the docker build.
COPY hindsight-manager/pyproject.toml hindsight-manager/uv.lock ./
RUN sed -i 's|/Users/liling/src/lab/xinyi-platform|/opt/xinyi-platform|g' pyproject.toml uv.lock && \
    uv sync --frozen

COPY hindsight-manager/hindsight_manager ./hindsight_manager
RUN uv pip install -e .


FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -s /bin/bash hindsight

COPY --from=builder /app /app
COPY --from=builder /opt/xinyi-platform /opt/xinyi-platform

USER hindsight

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "hindsight_manager.main:app", "--host", "0.0.0.0", "--port", "8001"]
