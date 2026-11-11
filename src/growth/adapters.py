from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from growth.contracts import Snapshot
from growth.db import Receipt, Row, VendorFault


class ContextAdapter(Protocol):
    def read(self, session: Session, tenant: str, customer: str, cart: str) -> Snapshot: ...


class JourneyAdapter(Protocol):
    def status(self, tenant: str, key: str) -> str | None: ...
    def trigger(self, tenant: str, key: str, journey: str) -> str: ...


class RetryableVendorError(Exception):
    pass


class PermanentVendorError(Exception):
    pass


class AmbiguousVendorError(Exception):
    pass


class MockContextAdapter:
    """Synthetic sources only. Missing or failed authority always fails closed."""

    def read(self, session: Session, tenant: str, customer: str, cart: str) -> Snapshot:
        source = session.get(Row, (tenant, "mock_context", cart))
        if source is None or source.data["customerRef"] != customer:
            return Snapshot(customerRef=customer, cartId=cart, identityKnown=False, consent=False)
        snapshot = Snapshot.model_validate(source.data)
        if session.get(Row, (tenant, "order", cart)) is not None:
            snapshot.ordered = True
        severe = session.scalars(select(Row).where(Row.tenant == tenant, Row.kind == "case")).all()
        snapshot.severeCase |= any(r.data["customerRef"] == customer for r in severe)
        return snapshot


class MockJourneyAdapter:
    """Independent durable vendor store models accepted-but-response-lost failures."""

    def __init__(self, db: Engine):
        self.db = db

    def mode(self, session: Session, tenant: str) -> str:
        fault = session.get(VendorFault, tenant)
        return fault.mode if fault else "healthy"

    def status(self, tenant: str, key: str) -> str | None:
        with Session(self.db) as session:
            if self.mode(session, tenant) == "unknown_status":
                raise AmbiguousVendorError("STATUS_UNAVAILABLE")
            row = session.scalar(
                select(Receipt).where(Receipt.tenant == tenant, Receipt.key == key)
            )
            return row.id if row else None

    def trigger(self, tenant: str, key: str, journey: str) -> str:
        # The adapter cannot accept free-form content, recipient addresses, prices or budgets.
        if journey != "cart-recovery-v1":
            raise PermanentVendorError("JOURNEY_NOT_APPROVED")
        with Session(self.db) as session, session.begin():
            mode = self.mode(session, tenant)
            if mode == "unavailable":
                raise RetryableVendorError("VENDOR_UNAVAILABLE")
            if mode == "permanent":
                raise PermanentVendorError("VENDOR_REJECTED")
            row = session.scalar(
                select(Receipt).where(Receipt.tenant == tenant, Receipt.key == key)
            )
            if row is None:
                row = Receipt(id=f"mock-{uuid4()}", tenant=tenant, key=key)
                session.add(row)
                session.flush()
            external = row.id
        if mode == "timeout_after_accept":
            raise AmbiguousVendorError("ACK_TIMEOUT")
        return external
