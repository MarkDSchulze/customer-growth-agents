"""Verify local infrastructure without printing private generated credentials."""

import asyncio
import os
import subprocess  # nosec B404
import sys
from contextlib import ExitStack
from pathlib import Path

from confluent_kafka.admin import AdminClient
from dotenv import dotenv_values
from temporalio.client import Client

from growth.db import engine

root = Path(__file__).resolve().parents[1]
local = dotenv_values(root / ".env")
env = dict(os.environ)
env.update({k: v for k, v in local.items() if v is not None})
owner_password = local["GROWTH_DB_PASSWORD"]
app_password = local["GROWTH_APP_DB_PASSWORD"]
env.update(
    {
        "GROWTH_DATABASE_URL": f"postgresql+psycopg://growth_app:{app_password}@localhost:5432/growth",
        "GROWTH_MIGRATION_URL": f"postgresql+psycopg://growth_owner:{owner_password}@localhost:5432/growth",
        "GROWTH_VENDOR_DATABASE_URL": f"postgresql+psycopg://growth_owner:{owner_password}@localhost:5432/vendor",
        "GROWTH_KAFKA_SERVERS": "localhost:19092",
        "GROWTH_TEMPORAL_ADDRESS": "localhost:7233",
        "GROWTH_EXECUTION": "temporal",
        "GROWTH_INTEGRATION": "1",
        "GROWTH_SANDBOX_URL": "http://localhost:8100",
        "GROWTH_SANDBOX_ALLOWED_HOSTS": '["localhost"]',
        "GROWTH_ALLOW_INTERNAL_SANDBOX": "true",
    }
)


async def await_dependencies() -> None:
    for attempt in range(45):
        try:
            with engine(env["GROWTH_MIGRATION_URL"]).connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            await asyncio.wait_for(Client.connect("localhost:7233"), timeout=2)
            AdminClient({"bootstrap.servers": "localhost:19092"}).list_topics(timeout=2)
            return
        except Exception:
            if attempt == 44:
                raise SystemExit(
                    "Infrastructure unavailable; inspect docker compose logs."
                ) from None
            await asyncio.sleep(1)


asyncio.run(await_dependencies())
subprocess.run(  # nosec B603
    [sys.executable, "scripts/migrate.py"], cwd=root, env=env, check=True
)
(root / "work").mkdir(exist_ok=True)
commands = [
    (
        "sandbox",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "growth.enterprise.sandbox:create_sandbox",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8100",
            "--no-access-log",
        ],
    ),
    ("event-worker", [sys.executable, "-m", "growth.event_worker"]),
    ("enterprise-worker", [sys.executable, "-m", "growth.enterprise.worker"]),
]
with ExitStack() as stack:
    processes = []
    for name, command in commands:
        log = stack.enter_context((root / "work" / f"{name}.log").open("w"))
        processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log))  # nosec B603
    try:
        result = subprocess.run(  # nosec B603
            [sys.executable, "-m", "pytest", "-m", "integration", "-q"],
            cwd=root,
            env=env,
            check=False,
        )
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=10)
raise SystemExit(result.returncode)
