-- Reference only. Apply scripts/migrate.py for atomic DDL, RLS and permissions.


CREATE TABLE enterprise_assignment (
	tenant VARCHAR(96) NOT NULL, 
	experiment VARCHAR(96) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	arm VARCHAR(16) NOT NULL, 
	created TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant, experiment, customer)
)

;


CREATE TABLE enterprise_audit (
	tenant VARCHAR(96) NOT NULL, 
	sequence INTEGER NOT NULL, 
	correlation VARCHAR(40) NOT NULL, 
	workflow VARCHAR(64) NOT NULL, 
	actor VARCHAR(96) NOT NULL, 
	operation VARCHAR(64) NOT NULL, 
	outcome VARCHAR(96) NOT NULL, 
	policy VARCHAR(96) NOT NULL, 
	purpose VARCHAR(32) NOT NULL, 
	region VARCHAR(32) NOT NULL, 
	previous_hash VARCHAR(64) NOT NULL, 
	record_hash VARCHAR(64) NOT NULL, 
	created TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant, sequence)
)

;


CREATE TABLE enterprise_event_receipt (
	tenant VARCHAR(96) NOT NULL, 
	id VARCHAR(40) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	workflow VARCHAR(64) NOT NULL, 
	PRIMARY KEY (tenant, id)
)

;


CREATE TABLE enterprise_identity_binding (
	tenant VARCHAR(96) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	shopify_customer VARCHAR(96) NOT NULL, 
	binding JSON NOT NULL, 
	PRIMARY KEY (tenant, customer)
)

;

CREATE INDEX ix_enterprise_identity_binding_shopify_customer ON enterprise_identity_binding (shopify_customer);


CREATE TABLE enterprise_ingest_window (
	tenant VARCHAR(96) NOT NULL, 
	minute INTEGER NOT NULL, 
	count INTEGER NOT NULL, 
	PRIMARY KEY (tenant, minute)
)

;


CREATE TABLE enterprise_mock_context (
	tenant VARCHAR(96) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	context JSON NOT NULL, 
	PRIMARY KEY (tenant, customer)
)

;


CREATE TABLE enterprise_order_evidence (
	tenant VARCHAR(96) NOT NULL, 
	order_ref VARCHAR(96) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	occurred TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant, order_ref)
)

;

CREATE INDEX ix_enterprise_order_evidence_customer ON enterprise_order_evidence (customer);


CREATE TABLE enterprise_outbox (
	tenant VARCHAR(96) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	region VARCHAR(32) NOT NULL, 
	workflow VARCHAR(64) NOT NULL, 
	event JSON NOT NULL, 
	published BOOLEAN NOT NULL, 
	created TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant, id)
)

;


CREATE TABLE enterprise_tenant (
	id VARCHAR(96) NOT NULL, 
	region VARCHAR(32) NOT NULL, 
	config JSON NOT NULL, 
	killed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (region IN ('us-east-1','eu-west-1','ap-southeast-2'))
)

;


CREATE TABLE enterprise_workflow (
	tenant VARCHAR(96) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	region VARCHAR(32) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	purpose VARCHAR(32) NOT NULL, 
	aggregate VARCHAR(96) NOT NULL, 
	signal VARCHAR(32) NOT NULL, 
	source VARCHAR(96) NOT NULL, 
	event_id VARCHAR(40) NOT NULL, 
	correlation VARCHAR(40) NOT NULL, 
	policy VARCHAR(96) NOT NULL, 
	generation INTEGER NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	created TIMESTAMP WITH TIME ZONE NOT NULL, 
	deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
	decision JSON, 
	plan_hash VARCHAR(64), 
	reason VARCHAR(96), 
	PRIMARY KEY (tenant, id), 
	CHECK (state IN ('RECEIVED','PLANNED','EXECUTING','APPROVAL_PENDING','COMPLETED','SUPPRESSED','HOLDOUT','CANCELLED','EXPIRED','FAILED_REVIEW','DRY_RUN'))
)

;

CREATE INDEX enterprise_work_queue ON enterprise_workflow (tenant, state, created);


CREATE TABLE enterprise_action (
	tenant VARCHAR(96) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	workflow VARCHAR(64) NOT NULL, 
	customer VARCHAR(96) NOT NULL, 
	domain VARCHAR(24) NOT NULL, 
	tool VARCHAR(48) NOT NULL, 
	parameters JSON NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason VARCHAR(96), 
	attempts INTEGER NOT NULL, 
	created TIMESTAMP WITH TIME ZONE NOT NULL, 
	reserved TIMESTAMP WITH TIME ZONE, 
	external_ref VARCHAR(160), 
	approved_hash VARCHAR(64), 
	approver VARCHAR(96), 
	approval_expires TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (tenant, id), 
	FOREIGN KEY(tenant, workflow) REFERENCES enterprise_workflow (tenant, id), 
	CHECK (attempts >= 0 AND attempts <= 3), 
	CHECK (state IN ('PLANNED','AWAITING_APPROVAL','ACCEPTED','SUPPRESSED','HOLDOUT','REJECTED','DRY_RUN','CANCELLED','EXPIRED','RECONCILING','FAILED_REVIEW','RETRY_PENDING','EXECUTING'))
)

;

CREATE INDEX enterprise_action_customer ON enterprise_action (tenant, customer, created);

CREATE INDEX enterprise_action_queue ON enterprise_action (tenant, state, created);
