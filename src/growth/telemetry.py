import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "at": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "operation": record.getMessage(),
        }
        for key in (
            "correlationId",
            "tenantId",
            "region",
            "workflowId",
            "policyVersion",
            "purpose",
            "status",
        ):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        return json.dumps(fields)


def configure() -> None:
    logger = logging.getLogger("growth")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
