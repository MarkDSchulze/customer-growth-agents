import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from growth.config import settings
    from growth.contracts import ActionIntent
    from growth.db import engine
    from growth.engine import TERMINAL, GrowthEngine
    from growth.policy import Policy
    from growth.workflow_client import connect

TASK_QUEUE = "growth-cart-recovery-v1"


class Activities:
    def __init__(self, core: GrowthEngine):
        self.core = core

    @activity.defn
    def plan(self, task: dict[str, str]) -> dict[str, Any]:
        return self.core.plan(task["tenant"], task["workflowId"])

    @activity.defn
    def execute(self, task: dict[str, str]) -> dict[str, Any]:
        return self.core.execute(task["tenant"], ActionIntent(workflowId=task["workflowId"]))

    @activity.defn
    def observe(self, task: dict[str, str]) -> str:
        return self.core.expire(task["tenant"], task["workflowId"])


@workflow.defn
class CartRecoveryWorkflow:
    @workflow.run
    async def run(self, task: dict[str, str]) -> str:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=10),
        )
        await workflow.execute_activity(
            "plan", task, start_to_close_timeout=timedelta(seconds=30), retry_policy=retry
        )
        while True:
            state: str = await workflow.execute_activity(
                "observe", task, start_to_close_timeout=timedelta(seconds=10), retry_policy=retry
            )
            if state != "APPROVAL_PENDING":
                break
            await workflow.sleep(timedelta(seconds=10))
        for attempt in range(int(task.get("maxAttempts", "3"))):
            result: dict[str, Any] = await workflow.execute_activity(
                "execute",
                task,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            if result["state"] != "RETRY_PENDING":
                break
            await workflow.sleep(timedelta(seconds=2**attempt))
        while True:
            state = await workflow.execute_activity(
                "observe",
                task,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=retry,
            )
            if state in TERMINAL:
                return str(state)
            await workflow.sleep(timedelta(seconds=30))


async def main() -> None:
    config = settings()
    core = GrowthEngine(
        engine(config.database_url),
        engine(config.vendor_database_url),
        Policy.load(config.policy_path),
    )
    activities = Activities(core)
    client = await connect(config)
    with ThreadPoolExecutor(max_workers=16) as pool:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[CartRecoveryWorkflow],
            activities=[activities.plan, activities.execute, activities.observe],
            activity_executor=pool,
            max_concurrent_activities=16,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
