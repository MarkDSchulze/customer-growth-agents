import json
import re
import secrets

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from growth.config import settings
from growth.db import VendorBase, engine
from growth.enterprise.contracts import Scope, Tool
from growth.enterprise.execution import SyntheticExecutor


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    key: str
    tool: Tool
    parameters: dict[str, str]


def create_sandbox() -> FastAPI:
    config = settings()
    db = engine(config.vendor_database_url)
    VendorBase.metadata.create_all(db)
    executor = SyntheticExecutor(db)
    authorized = json.loads(config.sandbox_bindings.get_secret_value())
    app = FastAPI(title="Synthetic enterprise connector sandbox", version="1.0.0")

    def authenticate(request: Request, body: Command) -> None:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        binding = authorized.get(body.scope.tenantId, {})
        expected = str(binding.get("token", ""))
        if (
            not expected
            or not secrets.compare_digest(token, expected)
            or binding.get("region") != body.scope.region
        ):
            raise HTTPException(401, "SANDBOX_BINDING_DENIED")
        if request.headers.get("Idempotency-Key") != body.key or not re.fullmatch(
            r"[a-f0-9]{64}", body.key
        ):
            raise HTTPException(400, "IDEMPOTENCY_KEY_REQUIRED")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "synthetic"}

    @app.post("/v1/status")
    def status(body: Command, request: Request) -> dict[str, str]:
        authenticate(request, body)
        external = executor.status(body.scope, body.key, body.tool, body.parameters)
        return (
            {"state": "accepted", "externalRef": external} if external else {"state": "not_found"}
        )

    @app.post("/v1/execute")
    def execute(body: Command, request: Request) -> dict[str, str]:
        authenticate(request, body)
        external = executor.execute(body.scope, body.key, body.tool, body.parameters)
        return {"state": "accepted", "externalRef": external}

    return app
