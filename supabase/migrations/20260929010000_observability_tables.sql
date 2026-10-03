-- Observability: persisted RAG traces and a usage ledger.
-- Follows 20260929000000_initial_schema.sql. Matches backend/app/models/rag_trace.py.

CREATE TABLE rag_traces (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    user_id uuid,
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    query text NOT NULL,
    strategy varchar(50),
    abstained boolean NOT NULL DEFAULT false,
    abstention_reason varchar(50),
    verification_status varchar(20),
    total_ms numeric(12, 2),
    cost_usd numeric(12, 6),
    spans jsonb,
    stages jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rag_traces_organization_id ON rag_traces (organization_id);
CREATE INDEX ix_rag_traces_org_created ON rag_traces (organization_id, created_at DESC);

CREATE TABLE usage_ledger (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    user_id uuid,
    trace_id uuid REFERENCES rag_traces (id) ON DELETE SET NULL,
    kind varchar(20) NOT NULL,
    model varchar(100),
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cost_usd numeric(12, 6) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_usage_ledger_organization_id ON usage_ledger (organization_id);
CREATE INDEX ix_usage_ledger_org_created ON usage_ledger (organization_id, created_at DESC);

-- Traces contain users' questions and usage exposes spend, so direct Supabase-client
-- reads are limited to owners/admins (the backend enforces the same in application code).
CREATE FUNCTION is_org_admin(org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM organization_members
        WHERE organization_id = org
          AND user_id = auth.uid()
          AND role IN ('owner', 'admin')
    );
$$;

ALTER TABLE rag_traces   ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY rag_traces_admin_read ON rag_traces FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
CREATE POLICY usage_ledger_admin_read ON usage_ledger FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
