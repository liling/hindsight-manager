# Hindsight Manager
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY hindsight_manager ./hindsight_manager
RUN uv pip install -e .


FROM python:3.11-slim

WORKDIR /app

RUN useradd -m -s /bin/bash hindsight

COPY --from=builder /app /app

USER hindsight

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "hindsight_manager.main:app", "--host", "0.0.0.0", "--port", "8001"]
