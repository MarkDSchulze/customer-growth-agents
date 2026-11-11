-- Additive v1 hardening. App role must be NOSUPERUSER NOBYPASSRLS.
ALTER TABLE growth_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE growth_record FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_records ON growth_record
  USING (tenant = current_setting('app.tenant_id', true))
  WITH CHECK (tenant = current_setting('app.tenant_id', true));
ALTER TABLE audit_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_record FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_audit ON audit_record
  USING (tenant = current_setting('app.tenant_id', true))
  WITH CHECK (tenant = current_setting('app.tenant_id', true));
CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit is append only';
END;
$$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_record
  FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE INDEX growth_record_kind_created ON growth_record (tenant, kind, created);
