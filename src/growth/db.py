from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenant_control"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    killed: Mapped[bool] = mapped_column(Boolean, default=False)


class Row(Base):
    """Tenant-keyed operational aggregate; kind selects a strictly validated DTO."""

    __tablename__ = "growth_record"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Audit(Base):
    __tablename__ = "audit_record"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant: Mapped[str] = mapped_column(String(96), index=True)
    correlation: Mapped[str] = mapped_column(String(96), index=True)
    operation: Mapped[str] = mapped_column(String(96))
    outcome: Mapped[str] = mapped_column(String(96))
    workflow: Mapped[str] = mapped_column(String(160), default="")
    actor: Mapped[str] = mapped_column(String(96))
    policy: Mapped[str] = mapped_column(String(96))
    purpose: Mapped[str] = mapped_column(String(32), default="cart_recovery")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VendorBase(DeclarativeBase):
    pass


class Receipt(VendorBase):
    __tablename__ = "mock_vendor_receipt"
    __table_args__ = (UniqueConstraint("tenant", "key"),)
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(96))
    key: Mapped[str] = mapped_column(String(160))


class VendorFault(VendorBase):
    __tablename__ = "mock_vendor_fault"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="healthy")


def engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    created = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(created, "connect")
        def enable_foreign_keys(connection: Any, record: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

    return created


@contextmanager
def transaction(db: Engine, tenant: str) -> Iterator[Session]:
    """Serialize tenant decisions, source updates, contact caps and emergency disablement."""
    with Session(db) as session:
        if db.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            if tenant == "__global__":
                session.execute(text("SELECT pg_advisory_xact_lock(474769884)"))
            else:
                session.execute(text("SELECT pg_advisory_xact_lock_shared(474769884)"))
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant}
            )
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
                {"tenant": tenant},
            )
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
