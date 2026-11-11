from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from growth.db import Base, VendorBase, now


class Organization(Base):
    __tablename__ = "enterprise_tenant"
    __table_args__ = (CheckConstraint("region IN ('us-east-1','eu-west-1','ap-southeast-2')"),)
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    killed: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomerFixture(Base):
    __tablename__ = "enterprise_mock_context"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    customer: Mapped[str] = mapped_column(String(96), primary_key=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)


class Workflow(Base):
    __tablename__ = "enterprise_workflow"
    __table_args__ = (
        Index("enterprise_work_queue", "tenant", "state", "created"),
        CheckConstraint(
            "state IN ('RECEIVED','PLANNED','EXECUTING','APPROVAL_PENDING','COMPLETED',"
            "'SUPPRESSED','HOLDOUT','CANCELLED','EXPIRED','FAILED_REVIEW','DRY_RUN')"
        ),
    )
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str] = mapped_column(String(32))
    customer: Mapped[str] = mapped_column(String(96))
    purpose: Mapped[str] = mapped_column(String(32))
    aggregate: Mapped[str] = mapped_column(String(96))
    signal: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(96))
    event_id: Mapped[str] = mapped_column(String(40))
    correlation: Mapped[str] = mapped_column(String(40))
    policy: Mapped[str] = mapped_column(String(96))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(96), nullable=True)


class Action(Base):
    __tablename__ = "enterprise_action"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant", "workflow"], ["enterprise_workflow.tenant", "enterprise_workflow.id"]
        ),
        Index("enterprise_action_customer", "tenant", "customer", "created"),
        Index("enterprise_action_queue", "tenant", "state", "created"),
        CheckConstraint("attempts >= 0 AND attempts <= 3"),
        CheckConstraint(
            "state IN ('PLANNED','AWAITING_APPROVAL','ACCEPTED','SUPPRESSED','HOLDOUT',"
            "'REJECTED','DRY_RUN','CANCELLED','EXPIRED','RECONCILING','FAILED_REVIEW',"
            "'RETRY_PENDING','EXECUTING')"
        ),
    )
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow: Mapped[str] = mapped_column(String(64))
    customer: Mapped[str] = mapped_column(String(96))
    domain: Mapped[str] = mapped_column(String(24))
    tool: Mapped[str] = mapped_column(String(48))
    parameters: Mapped[dict[str, str]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), default="PLANNED")
    reason: Mapped[str | None] = mapped_column(String(96), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reserved: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approver: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approval_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Receipt(Base):
    __tablename__ = "enterprise_event_receipt"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    workflow: Mapped[str] = mapped_column(String(64))


class Assignment(Base):
    __tablename__ = "enterprise_assignment"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    experiment: Mapped[str] = mapped_column(String(96), primary_key=True)
    customer: Mapped[str] = mapped_column(String(96), primary_key=True)
    arm: Mapped[str] = mapped_column(String(16))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Outbox(Base):
    __tablename__ = "enterprise_outbox"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str] = mapped_column(String(32))
    workflow: Mapped[str] = mapped_column(String(64))
    event: Mapped[dict[str, Any]] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Journal(Base):
    __tablename__ = "enterprise_audit"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    correlation: Mapped[str] = mapped_column(String(40))
    workflow: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(96))
    operation: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(96))
    policy: Mapped[str] = mapped_column(String(96))
    purpose: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(32))
    previous_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VendorRecord(VendorBase):
    __tablename__ = "enterprise_vendor_record"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str] = mapped_column(String(32))
    tool: Mapped[str] = mapped_column(String(48))
    payload_hash: Mapped[str] = mapped_column(String(64))
    external_ref: Mapped[str] = mapped_column(String(160))


class OrderEvidence(Base):
    __tablename__ = "enterprise_order_evidence"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    order_ref: Mapped[str] = mapped_column(String(96), primary_key=True)
    customer: Mapped[str] = mapped_column(String(96), index=True)
    occurred: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityRecord(Base):
    __tablename__ = "enterprise_identity_binding"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    customer: Mapped[str] = mapped_column(String(96), primary_key=True)
    shopify_customer: Mapped[str] = mapped_column(String(96), index=True)
    binding: Mapped[dict[str, Any]] = mapped_column(JSON)


class IngestWindow(Base):
    __tablename__ = "enterprise_ingest_window"
    tenant: Mapped[str] = mapped_column(String(96), primary_key=True)
    minute: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
