-- Audit log of agent tool calls (every attempt, including denied/invalid/failed ones).
-- Matches backend/app/models/tool_audit.py.

CREATE TABLE tool_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    user_id uuid,
    run_id uuid NOT NULL,
    trace_id uuid,
    seq integer NOT NULL DEFAULT 0,
    tool varchar(60) NOT NULL,
    arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(20) NOT NULL,
    duration_ms numeric(12, 2) NOT NULL DEFAULT 0,
    result_chunks integer NOT NULL DEFAULT 0,
    detail text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_tool_audit_organization_id ON tool_audit (organization_id);
CREATE INDEX ix_tool_audit_run_id ON tool_audit (run_id);
CREATE INDEX ix_tool_audit_org_created ON tool_audit (organization_id, created_at DESC);

-- Arguments can contain users' questions: owners/admins only, like traces.
ALTER TABLE tool_audit ENABLE ROW LEVEL SECURITY;
CREATE POLICY tool_audit_admin_read ON tool_audit FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
