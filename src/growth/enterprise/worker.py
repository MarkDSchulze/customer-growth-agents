import asyncio
import json
import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from confluent_kafka import Consumer, Producer
    from sqlalchemy import select
    from growth.broker import configuration
    from growth.config import Settings, settings
    from growth.contracts import Principal
    from growth.engine import DomainError
    from growth.enterprise.contracts import SignalEvent
    from growth.enterprise.models import Outbox, Workflow
    from growth.enterprise.runtime import create_service
    from growth.enterprise.service import FINAL, EnterpriseService
    from growth.enterprise.storage import unit
    from growth.workflow_client import connect

logger = logging.getLogger("growth.enterprise.worker")


def queue(region: str) -> str:
    return f"growth-enterprise-v2-{region}"


class EnterpriseActivities:
    def __init__(self, core: EnterpriseService):
        self.core = core

    @activity.defn(name="enterprise_plan")
    def plan(self, task: dict[str, str]) -> dict[str, Any]:
        if task["region"] != self.core.region:
            raise ValueError("WORKER_REGION_MISMATCH")
        return self.core.plan(task["tenant"], task["workflowId"])

    @activity.defn(name="enterprise_step")
    def step(self, task: dict[str, str]) -> str:
        if task["region"] != self.core.region:
            raise ValueError("WORKER_REGION_MISMATCH")
        return str(self.core.execute(task["tenant"], task["workflowId"])["state"])

    @activity.defn(name="enterprise_state")
    def state(self, task: dict[str, str]) -> str:
        if task["region"] != self.core.region:
            raise ValueError("WORKER_REGION_MISMATCH")
        return self.core.observe(task["tenant"], task["workflowId"])


@workflow.defn
class EnterpriseWorkflow:
    @workflow.run
    async def run(self, task: dict[str, str]) -> str:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=10),
        )
        await workflow.execute_activity(
            "enterprise_plan",
            task,
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=retry,
        )
        while True:
            state: str = await workflow.execute_activity(
                "enterprise_state",
                task,
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=retry,
            )
            if state in FINAL:
                return state
            # Approved actions in the plan may execute while other domains await human review.
            state = await workflow.execute_activity(
                "enterprise_step",
                task,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=retry,
            )
            if state in FINAL:
                return state
            await workflow.sleep(timedelta(seconds=10 if state == "APPROVAL_PENDING" else 2))


def bindings(config: Settings) -> dict[str, dict[str, str]]:
    raw = json.loads(config.source_bindings)
    if not isinstance(raw, dict):
        raise ValueError("SOURCE_BINDINGS_INVALID")
    result = {}
    for source, value in raw.items():
        identity = Principal(
            subject=source,
            tenant=value["tenantId"],
            region=value["region"],
            role="producer",
            purposes=[
                "cart_recovery",
                "lead_qualification",
                "audience_activation",
                "commerce_personalization",
                "service_recovery",
            ],
        )
        result[source] = {"tenantId": identity.tenant, "region": identity.region}
    return result


def dispatch(
    core: EnterpriseService, producer: Any, source_bindings: dict[str, dict[str, str]]
) -> int:
    tenants = {b["tenantId"] for b in source_bindings.values() if b["region"] == core.region}
    total = 0
    for tenant in sorted(tenants):
        with unit(core.db, tenant) as session:
            rows = session.scalars(
                select(Outbox)
                .where(
                    Outbox.tenant == tenant,
                    Outbox.region == core.region,
                    Outbox.published.is_(False),
                )
                .order_by(Outbox.created)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            for row in rows:
                failures: list[str] = []

                def delivered(error: Any, message: Any, failures: list[str] = failures) -> None:
                    if error:
                        failures.append("PUBLISH_UNCONFIRMED")

                producer.produce(
                    "growth.signal.v2",
                    key=f"{tenant}:{row.workflow}".encode(),
                    value=json.dumps(row.event).encode(),
                    on_delivery=delivered,
                )
                pending = producer.flush(5)
                if pending or failures:
                    raise RuntimeError("BROKER_PUBLISH_UNCONFIRMED")
                row.published = True
                total += 1
    return total


async def event_loop(core: EnterpriseService, config: Settings, client: Client) -> None:
    source_bindings = bindings(config)
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
            "group.id": f"growth-enterprise-v2-{config.region}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(["growth.signal.v2"])
    try:
        while True:
            await asyncio.to_thread(dispatch, core, producer, source_bindings)
            message = await asyncio.to_thread(consumer.poll, 0.5)
            if message is None or message.error():
                continue
            try:
                raw = message.value() or b""
                if len(raw) > 65536:
                    raise ValueError("SOURCE_MESSAGE_TOO_LARGE")
                event = SignalEvent.model_validate_json(raw)
                binding = source_bindings.get(event.source)
                if (
                    not binding
                    or binding["tenantId"] != event.tenantId
                    or (binding["region"] != event.region or event.region != config.region)
                ):
                    raise ValueError("SOURCE_BINDING_DENIED")
                identity = Principal(
                    subject=event.source,
                    tenant=event.tenantId,
                    region=event.region,
                    role="producer",
                    purposes=[
                        "cart_recovery",
                        "lead_qualification",
                        "audience_activation",
                        "commerce_personalization",
                        "service_recovery",
                    ],
                )
                result = core.ingest(identity, event)
                with unit(core.db, event.tenantId) as session:
                    record = session.get(Workflow, (event.tenantId, result["workflowId"]))
                    if record is None:
                        raise ValueError("WORKFLOW_MISSING")
                    generation = record.generation
                try:
                    await client.start_workflow(
                        EnterpriseWorkflow.run,
                        {
                            "tenant": event.tenantId,
                            "region": event.region,
                            "workflowId": result["workflowId"],
                        },
                        id=f"enterprise-{event.region}-{result['workflowId']}-{generation}",
                        task_queue=queue(event.region),
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    )
                except WorkflowAlreadyStartedError:
                    pass
            except (ValueError, KeyError, DomainError):
                logger.warning("source.contract_or_scope_rejected")
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()


async def main() -> None:
    config = settings()
    core = create_service(config)
    client = await connect(config)
    activities = EnterpriseActivities(core)
    with ThreadPoolExecutor(max_workers=config.worker_concurrency) as pool:
        worker = Worker(
            client,
            task_queue=queue(config.region),
            workflows=[EnterpriseWorkflow],
            activities=[activities.plan, activities.step, activities.state],
            activity_executor=pool,
            max_concurrent_activities=config.worker_concurrency,
        )
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stopped.set)
        broker_task = asyncio.create_task(event_loop(core, config, client))
        stop_task = asyncio.create_task(stopped.wait())
        worker_task = asyncio.create_task(worker.run())
        try:
            done, _ = await asyncio.wait(
                [broker_task, stop_task, worker_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task is not stop_task:
                    task.result()
        finally:
            broker_task.cancel()
            stop_task.cancel()
            await worker.shutdown()
            await asyncio.gather(broker_task, stop_task, worker_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
