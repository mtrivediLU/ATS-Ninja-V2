# ATS-Ninja-V2 API image.
# Build context is the repository root so the engine (a workspace dependency)
# can be installed alongside the API.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the engine first (its own dependency graph is more stable than the
# app's), then the API. Installing the engine before the API lets pip resolve
# the `ats-engine` requirement from the local build rather than an index.
COPY packages/engine ./packages/engine
RUN pip install ./packages/engine

COPY apps/api ./apps/api
RUN pip install ./apps/api

WORKDIR /app/apps/api

EXPOSE 8000

# Liveness check without adding curl to the slim image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
