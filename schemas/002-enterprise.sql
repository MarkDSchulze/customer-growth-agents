-- Run atomically with normalized table creation. No business data is backfilled or destroyed.
ALTER TABLE enterprise_tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_tenant FORCE ROW LEVEL SECURITY;
CREATE POLICY enterprise_tenant_scope ON enterprise_tenant
 USING (id=current_setting('app.tenant_id',true))
 WITH CHECK (id=current_setting('app.tenant_id',true));
DO $$
DECLARE relation_name text;
BEGIN
 FOREACH relation_name IN ARRAY ARRAY['enterprise_mock_context','enterprise_workflow',
 'enterprise_action','enterprise_event_receipt','enterprise_assignment','enterprise_outbox',
 'enterprise_audit','enterprise_order_evidence','enterprise_identity_binding','enterprise_ingest_window'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', relation_name);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', relation_name);
  EXECUTE format('CREATE POLICY tenant_scope ON %I USING (tenant=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant=current_setting(''app.tenant_id'',true))', relation_name);
 END LOOP;
END $$;
CREATE TRIGGER enterprise_audit_immutable BEFORE UPDATE OR DELETE ON enterprise_audit
 FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
