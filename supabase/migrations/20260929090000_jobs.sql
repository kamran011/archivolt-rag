-- Durable background jobs (ingestion today). Matches backend/app/models/job.py.
-- Workers claim with FOR UPDATE SKIP LOCKED; see backend/app/domains/jobs/.

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organizations (id) ON DELETE CASCADE,
    kind varchar(60) NOT NULL,
    dedupe_key varchar(200),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(20) NOT NULL DEFAULT 'queued',
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    run_after timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz,
    locked_by varchar(100),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CONSTRAINT jobs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'dead'))
);
CREATE INDEX ix_jobs_organization_id ON jobs (organization_id);
CREATE INDEX ix_jobs_claim ON jobs (run_after) WHERE status = 'queued';
CREATE UNIQUE INDEX uq_jobs_active_dedupe ON jobs (kind, dedupe_key)
    WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL;

-- Job payloads and errors can reference internals: admins only.
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_admin_read ON jobs FOR SELECT TO authenticated
    USING (organization_id IS NOT NULL AND is_org_admin(organization_id));
