import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from growth.enterprise.contracts import Scope
from growth.enterprise.models import Journal


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@contextmanager
def unit(db: Engine, tenant: str, customer: str = "", exclusive: bool = False) -> Iterator[Session]:
    """Regional RLS and per-customer writes; shared tenant/global emergency guards."""
    with Session(db) as session:
        if db.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant}
            )
            session.execute(text("SELECT pg_advisory_xact_lock_shared(474769884)"))
            function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
            # Function is selected exclusively by code; identifiers are never request parameters.
            if function == "pg_advisory_xact_lock":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,0))"),
                    {"tenant": tenant},
                )
            else:
                session.execute(
                    text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:tenant,0))"),
                    {"tenant": tenant},
                )
            if customer:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,1))"),
                    {"key": json.dumps([tenant, customer])},
                )
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def journal(session: Session, scope: Scope, operation: str, outcome: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,2))"),
            {"tenant": scope.tenantId},
        )
    last = session.scalar(
        select(Journal)
        .where(Journal.tenant == scope.tenantId)
        .order_by(Journal.sequence.desc())
        .limit(1)
    )
    seq, previous = (last.sequence + 1, last.record_hash) if last else (1, "0" * 64)
    stamp = datetime.now(UTC)
    fields = {
        "created": stamp.isoformat(),
        "tenant": scope.tenantId,
        "sequence": seq,
        "previous_hash": previous,
        "correlation": scope.correlationId,
        "workflow": scope.workflowId,
        "actor": scope.actor,
        "operation": operation,
        "outcome": outcome,
        "policy": scope.policyVersion,
        "purpose": scope.purpose,
        "region": scope.region,
    }
    session.add(Journal(**{**fields, "created": stamp}, record_hash=digest(fields)))
    session.flush()
