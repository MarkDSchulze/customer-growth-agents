from typing import Any

import httpx
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor, RequestInfo
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

from growth.config import Settings

_provider: TracerProvider | None = None


def initialize(config: Settings) -> TracerProvider | None:
    global _provider
    if not config.otel_enabled:
        return None
    if _provider is None:
        _provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "customer-growth",
                    "service.version": "0.2.0",
                    "cloud.region": config.region,
                }
            )
        )
        if config.otel_endpoint:
            _provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=config.otel_endpoint))
            )
    return _provider


def instrument_app(app: FastAPI, provider: TracerProvider) -> None:
    def redact(span: Span, scope: dict[str, Any]) -> None:
        # Unknown query parameters may contain PII; never retain them in telemetry.
        path = scope.get("path", "/")
        span.set_attribute("url.query", "")
        for field in ("url.full", "http.url", "http.target"):
            span.set_attribute(field, path)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        server_request_hook=redact,
        excluded_urls="healthz,readyz,metrics",
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
    )


def instrument_client(client: httpx.Client) -> httpx.Client:
    if _provider:

        def redact(span: Span, request: RequestInfo) -> None:
            sanitized = (
                str(request.url.copy_with(query=None))
                if isinstance(request.url, httpx.URL)
                else request.url[3].split(b"?", 1)[0].decode("ascii", errors="replace")
            )
            for field in ("url.full", "http.url", "http.target"):
                span.set_attribute(field, sanitized)

        HTTPXClientInstrumentor.instrument_client(
            client, tracer_provider=_provider, request_hook=redact
        )
    return client
