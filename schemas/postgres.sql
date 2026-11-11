-- Generated reference DDL. Run scripts/migrate.py, including 001-tenant-isolation.sql.

CREATE TABLE audit_record (
	seq SERIAL NOT NULL,
	tenant VARCHAR(96) NOT NULL,
	correlation VARCHAR(96) NOT NULL,
	operation VARCHAR(96) NOT NULL,
	outcome VARCHAR(96) NOT NULL,
	workflow VARCHAR(160) NOT NULL,
	actor VARCHAR(96) NOT NULL,
	policy VARCHAR(96) NOT NULL,
	purpose VARCHAR(32) NOT NULL,
	created TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (seq)
)

;

CREATE TABLE growth_record (
	tenant VARCHAR(96) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	id VARCHAR(160) NOT NULL,
	data JSON NOT NULL,
	created TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (tenant, kind, id)
)

;

CREATE TABLE tenant_control (
	id VARCHAR(96) NOT NULL,
	killed BOOLEAN NOT NULL,
	PRIMARY KEY (id)
)

;
