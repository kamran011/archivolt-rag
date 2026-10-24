create table if not exists org_invitations (
    id         uuid primary key default gen_random_uuid(),
    org_id     uuid not null references organizations(id) on delete cascade,
    email      text not null,
    role       text not null default 'member',
    invited_by uuid not null,
    accepted_at timestamptz,
    created_at timestamptz not null default now()
);

create index ix_org_invitations_org_id   on org_invitations (org_id);
create index ix_org_invitations_email    on org_invitations (email);
-- Prevent re-inviting to the same org when a pending invite already exists
create unique index uq_org_invitation_pending
    on org_invitations (org_id, lower(email))
    where accepted_at is null;
