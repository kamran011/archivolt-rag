-- Evaluation datasets and runs. Matches backend/app/models/eval_run.py.
-- Per-case results live in eval_runs.results (one jsonb document per run).

CREATE TABLE eval_datasets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name varchar(200) NOT NULL,
    cases jsonb NOT NULL,
    case_count integer NOT NULL,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_eval_datasets_organization_id ON eval_datasets (organization_id);

CREATE TABLE eval_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    dataset_id uuid NOT NULL REFERENCES eval_datasets (id) ON DELETE CASCADE,
    knowledge_base_ids jsonb NOT NULL,
    config jsonb NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'queued',
    summary jsonb,
    results jsonb,
    total_cases integer,
    failed_cases integer,
    error text,
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CONSTRAINT eval_runs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);
CREATE INDEX ix_eval_runs_org_created ON eval_runs (organization_id, created_at DESC);
CREATE INDEX ix_eval_runs_dataset_id ON eval_runs (dataset_id);

-- Datasets can contain sensitive questions and canaries: admins only.
ALTER TABLE eval_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY eval_datasets_admin_read ON eval_datasets FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
CREATE POLICY eval_runs_admin_read ON eval_runs FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
