# ExperienceOS ledger web demo — container image.
#
# Build context is the repo root:
#   docker build -f deploy/Dockerfile -t experienceos-web .
#
# The Qwen (Alibaba Cloud DashScope) credential is NEVER baked in — it is
# injected at run time:
#   docker run -p 8517:8517 -e QWEN_API_KEY=... experienceos-web
#
# The core `experienceos` package has zero third-party dependencies, so the
# image stays small and builds in seconds.

FROM python:3.12-slim

WORKDIR /app

# Copy the runtime source (the .dockerignore excludes .env, .git, tests, etc.)
COPY pyproject.toml README.md ./
COPY experienceos ./experienceos
COPY demo ./demo
COPY web ./web

# Install the package (zero deps); demo/ and web/ resolve via PYTHONPATH.
RUN pip install --no-cache-dir . \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    EXPERIENCEOS_WEB_HOST=0.0.0.0 \
    EXPERIENCEOS_WEB_PORT=8517

EXPOSE 8517

# QWEN_API_KEY is supplied by `docker run -e ...` or the cloud service's
# secret/env configuration — not present in this image.
CMD ["python", "web/server.py"]
