import asyncio
import hashlib
import json
import logging
from typing import Any

from confluent_kafka import Consumer, Producer
from pydantic import ValidationError
from sqlalchemy import select
from temporalio.exceptions import WorkflowAlreadyStartedError

from growth.broker import configuration
from growth.config import settings
from growth.contracts import Event
from growth.db import Row, Tenant, engine, transaction
from growth.engine import DomainError, GrowthEngine
from growth.policy import Policy
from growth.temporal_worker import TASK_QUEUE, CartRecoveryWorkflow
from growth.workflow_client import connect

logger = logging.getLogger("growth.events")
TOPICS = ["commerce.cart_abandoned.v1", "commerce.order_placed.v1", "service.case_escalated.v1"]


def publish_outbox(core: GrowthEngine, producer: Any) -> int:
    with core.db.connect() as conn:
        tenants = list(conn.execute(select(Tenant.id)).scalars())
    published = 0
    for tenant in tenants:
        with transaction(core.db, tenant) as session:
            rows = session.scalars(
                select(Row).where(Row.tenant == tenant, Row.kind == "outbox")
            ).all()
            for row in rows:
                if row.data["published"]:
                    continue
                event = Event.model_validate(row.data["event"])
                errors: list[str] = []
                producer.produce(
                    event.eventType,
                    key=f"{tenant}:{event.aggregateId}".encode(),
                    value=event.model_dump_json().encode(),
                    on_delivery=lambda err, msg, errors=errors: (
                        errors.append(str(err)) if err else None
                    ),
                )
                pending = producer.flush(10)
                if pending or errors:
                    raise RuntimeError("BROKER_PUBLISH_UNCONFIRMED")
                row.data = {**row.data, "published": True}
                published += 1
    return published


async def main() -> None:
    config = settings()
    core = GrowthEngine(
        engine(config.database_url),
        engine(config.vendor_database_url),
        Policy.load(config.policy_path),
    )
    client = await connect(config)
    producer = Producer(
        {
            **configuration(config),
            "enable.idempotence": True,
            "delivery.timeout.ms": 10000,
            "request.timeout.ms": 5000,
        }
    )
    consumer = Consumer(
        {
            **configuration(config),
            "group.id": "growth-cart-recovery-v1",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(TOPICS)
    try:
        while True:
            await asyncio.to_thread(publish_outbox, core, producer)
            message = await asyncio.to_thread(consumer.poll, 0.5)
            if message is None:
                continue
            if message.error():
                logger.warning("broker_poll_error")
                continue
            try:
                event = Event.model_validate_json(message.value() or b"null")
                # Synthetic tenant binding; production requires per-source identities and ACLs.
                if event.tenantId != "tenant-demo" or event.eventType != message.topic():
                    raise DomainError("SOURCE_TENANT_OR_TOPIC_MISMATCH")
                result = core.ingest("tenant-demo", event)
                if result.get("workflowId"):
                    try:
                        await client.start_workflow(
                            CartRecoveryWorkflow.run,
                            {
                                "tenant": "tenant-demo",
                                "workflowId": result["workflowId"],
                                "maxAttempts": str(core.policy.maxAttempts),
                            },
                            id=f"growth-{result['workflowId']}",
                            task_queue=TASK_QUEUE,
                        )
                    except WorkflowAlreadyStartedError:
                        pass
            except (ValidationError, DomainError, json.JSONDecodeError):
                # Retain transport references only, never the rejected payload.
                key = hashlib.sha256(message.value() or b"").hexdigest()
                with transaction(core.db, "tenant-demo") as session:
                    core.put(
                        session,
                        "tenant-demo",
                        "transport_dlq",
                        key,
                        {
                            "hash": key,
                            "topic": message.topic(),
                            "partition": message.partition(),
                            "offset": message.offset(),
                            "reason": "CONTRACT_OR_AUTH_REJECTED",
                        },
                    )
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()


if __name__ == "__main__":
    asyncio.run(main())
