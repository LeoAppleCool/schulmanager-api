# syntax=docker/dockerfile:1

# --- build stage ---
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir build \
    && python -m build --wheel --outdir /build/dist

# --- api runtime stage ---
FROM python:3.12-slim AS api

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown app:app /app/data

USER app

EXPOSE 8000

CMD ["uvicorn", "schulmanager_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
