"""Versioned additive schema bootstrap; migrations run separately from application workers."""

import os
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from growth.config import settings
from growth.db import Base, VendorBase, engine

config = settings()
admin_url = os.environ.get("GROWTH_MIGRATION_URL", config.database_url)
db = engine(admin_url)
Base.metadata.create_all(db)
if db.dialect.name == "postgresql":
    vendor_name = make_url(config.vendor_database_url).database
    with db.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        raw_connection = connection.connection.driver_connection
        if not isinstance(raw_connection, psycopg.Connection):
            raise TypeError("PostgreSQL driver required")
        found = raw_connection.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (vendor_name,)
        ).fetchone()
        if not found:
            raw_connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(str(vendor_name)))
            )
VendorBase.metadata.create_all(engine(config.vendor_database_url))
with db.begin() as conn:
    conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migration (version INTEGER PRIMARY KEY)"))
    present = conn.scalar(text("SELECT version FROM schema_migration WHERE version=1"))
    if present is None:
        if db.dialect.name == "postgresql":
            raw = conn.connection.driver_connection
            if not isinstance(raw, psycopg.Connection):
                raise TypeError("PostgreSQL driver required")
            raw.execute(Path("schemas/001-tenant-isolation.sql").read_text())
        conn.execute(text("INSERT INTO schema_migration (version) VALUES (1)"))
    if db.dialect.name == "postgresql" and os.environ.get("GROWTH_APP_DB_PASSWORD"):
        raw = conn.connection.driver_connection
        if not isinstance(raw, psycopg.Connection):
            raise TypeError("PostgreSQL driver required")
        exists = raw.execute("SELECT 1 FROM pg_roles WHERE rolname='growth_app'").fetchone()
        if not exists:
            raw.execute(
                sql.SQL("CREATE ROLE growth_app LOGIN PASSWORD {}").format(
                    sql.Literal(os.environ["GROWTH_APP_DB_PASSWORD"])
                )
            )
        database = make_url(admin_url).database
        raw.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO growth_app").format(
                sql.Identifier(str(database))
            )
        )
        raw.execute("GRANT USAGE ON SCHEMA public TO growth_app")
        raw.execute("GRANT SELECT, INSERT, UPDATE ON tenant_control, growth_record TO growth_app")
        raw.execute("GRANT SELECT, INSERT ON audit_record TO growth_app")
        raw.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO growth_app")
print(
    "Schema version 1 ready. Rollback is application rollback; preserve audit and vendor receipts."
)
