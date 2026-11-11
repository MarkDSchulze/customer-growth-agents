# syntax=docker/dockerfile:1
FROM python:3.12.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    UV_NO_CACHE=1 uv sync --frozen --no-dev --extra aws && \
    chmod -R a+rX /app && useradd --create-home --uid 10001 growth
USER growth
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn","growth.api:app","--host","0.0.0.0","--port","8000","--no-access-log"]
