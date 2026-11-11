"""Explicit contract regeneration; CI uses --check and rejects drift."""

import argparse
import json
from pathlib import Path

import yaml
from pydantic import BaseModel

from growth.api import create_app
from growth.contracts import ActionExecuted, CartAbandoned, CaseEscalated, Event, OrderPlaced

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
openapi = create_app().openapi()
schema = Event.model_json_schema()

models: list[type[BaseModel]] = [CartAbandoned, OrderPlaced, CaseEscalated, ActionExecuted]
types = [
    "commerce.cart_abandoned.v1",
    "commerce.order_placed.v1",
    "service.case_escalated.v1",
    "growth.action_executed.v1",
]
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["allOf"] = [
    {
        "if": {"properties": {"eventType": {"const": kind}}},
        "then": {"properties": {"data": model.model_json_schema()}},
    }
    for kind, model in zip(types, models, strict=True)
]
for file, data in [
    ("contracts/openapi.json", openapi),
    ("contracts/openapi.yaml", openapi),
    ("contracts/event.schema.json", schema),
]:
    content = (
        yaml.safe_dump(data, sort_keys=True)
        if file.endswith(".yaml")
        else json.dumps(data, indent=2, sort_keys=True) + "\n"
    )
    path = Path(file)
    if args.check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit(f"Contract drift: {file}; version and regenerate explicitly.")
    else:
        path.write_text(content)
print("Contracts match implementation." if args.check else "Contracts exported.")
