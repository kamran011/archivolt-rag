-- Human handoff (V3): conversations escalated to the team. Matches
-- backend/app/models/escalation.py.

CREATE TABLE escalations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    user_id uuid,
    message_id uuid,
    trace_id uuid,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    status varchar(20) NOT NULL DEFAULT 'open',
    delivery jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by uuid
);
CREATE INDEX ix_escalations_organization_id ON escalations (organization_id);
CREATE INDEX ix_escalations_conversation_id ON escalations (conversation_id);
CREATE INDEX ix_escalations_org_created ON escalations (organization_id, created_at DESC);
-- At most one open escalation per conversation: repeat triggers do not re-notify the team.
CREATE UNIQUE INDEX ux_escalations_open_conversation ON escalations (conversation_id)
    WHERE status = 'open';

-- Escalations expose users' conversations: owners/admins only, like traces.
ALTER TABLE escalations ENABLE ROW LEVEL SECURITY;
CREATE POLICY escalations_admin_read ON escalations FOR SELECT TO authenticated
    USING (is_org_admin(organization_id));
