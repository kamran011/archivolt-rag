-- Groundtruth initial schema.
--
-- DERIVED FROM the SQLAlchemy models in backend/app/models/ (the authoritative
-- DB spec, docs/GROUNDTRUTH_DATABASE_SPEC.md, is still pending). If that spec
-- differs, add a follow-up migration rather than editing this one.
--
-- Enum type names match SQLAlchemy's default naming so the ORM works unchanged.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE chunkstrategy AS ENUM ('fixed', 'structure_aware');
CREATE TYPE kbstatus AS ENUM ('active', 'archived');
CREATE TYPE orgrole AS ENUM ('owner', 'admin', 'member', 'viewer');
CREATE TYPE filetype AS ENUM ('pdf', 'docx', 'md', 'txt', 'html', 'csv', 'json');
CREATE TYPE documentstatus AS ENUM ('pending', 'parsing', 'chunking', 'embedding', 'ready', 'failed');
CREATE TYPE authoritytier AS ENUM ('authoritative', 'standard', 'draft');
CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system');

CREATE TABLE organizations (
	name VARCHAR(200) NOT NULL,
	slug VARCHAR(100) NOT NULL,
	description TEXT,
	settings JSONB NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_organizations_slug ON organizations (slug);
CREATE TABLE knowledge_bases (
	organization_id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	description TEXT,
	embedding_model VARCHAR(100) NOT NULL,
	chunk_strategy chunkstrategy NOT NULL,
	chunk_size INTEGER NOT NULL,
	chunk_overlap INTEGER NOT NULL,
	status kbstatus NOT NULL,
	document_count INTEGER NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);
CREATE INDEX ix_knowledge_bases_organization_id ON knowledge_bases (organization_id);
CREATE TABLE organization_members (
	organization_id UUID NOT NULL,
	user_id UUID NOT NULL,
	role orgrole NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_org_member UNIQUE (organization_id, user_id),
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);
CREATE INDEX ix_organization_members_user_id ON organization_members (user_id);
CREATE INDEX ix_organization_members_organization_id ON organization_members (organization_id);
CREATE TABLE conversations (
	organization_id UUID NOT NULL,
	knowledge_base_id UUID,
	user_id UUID NOT NULL,
	title VARCHAR(500),
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE SET NULL
);
CREATE INDEX ix_conversations_organization_id ON conversations (organization_id);
CREATE INDEX ix_conversations_knowledge_base_id ON conversations (knowledge_base_id);
CREATE INDEX ix_conversations_user_id ON conversations (user_id);
CREATE TABLE documents (
	organization_id UUID NOT NULL,
	knowledge_base_id UUID NOT NULL,
	title VARCHAR(500) NOT NULL,
	file_name VARCHAR(500) NOT NULL,
	file_type filetype NOT NULL,
	file_size BIGINT NOT NULL,
	storage_path VARCHAR(1000) NOT NULL,
	status documentstatus NOT NULL,
	page_count INTEGER,
	chunk_count INTEGER NOT NULL,
	parsing_metadata JSONB,
	error_message TEXT,
	uploaded_by UUID,
	version INTEGER NOT NULL,
	is_current BOOLEAN NOT NULL,
	supersedes_document_id UUID,
	superseded_at TIMESTAMP WITH TIME ZONE,
	effective_date TIMESTAMP WITH TIME ZONE,
	authority_tier authoritytier NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE,
	FOREIGN KEY(supersedes_document_id) REFERENCES documents (id) ON DELETE SET NULL
);
CREATE INDEX ix_documents_knowledge_base_id ON documents (knowledge_base_id);
CREATE INDEX ix_documents_organization_id ON documents (organization_id);
CREATE TABLE chunks (
	organization_id UUID NOT NULL,
	document_id UUID NOT NULL,
	knowledge_base_id UUID NOT NULL,
	content TEXT NOT NULL,
	chunk_index INTEGER NOT NULL,
	token_count INTEGER NOT NULL,
	metadata JSONB NOT NULL,
	embedding VECTOR(1536),
	fts_vector TSVECTOR,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);
CREATE INDEX ix_chunks_kb_org ON chunks (knowledge_base_id, organization_id);
CREATE INDEX ix_chunks_organization_id ON chunks (organization_id);
CREATE INDEX ix_chunks_doc ON chunks (document_id);
CREATE TABLE messages (
	conversation_id UUID NOT NULL,
	role messagerole NOT NULL,
	content TEXT NOT NULL,
	citations JSONB,
	retrieval_metadata JSONB,
	token_usage JSONB,
	abstained BOOLEAN NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);
CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

-- ---------------------------------------------------------------------------
-- Search indexes
-- ---------------------------------------------------------------------------

-- Vector search uses cosine distance (see retrieval/engines/vector_engine.py).
CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_chunks_fts ON chunks USING gin (fts_vector);
CREATE INDEX ix_documents_kb_current ON documents (knowledge_base_id) WHERE is_current;

-- The application never writes fts_vector; keep it in sync in the database.
-- 'english' matches plainto_tsquery('english', ...) in keyword_engine.py.
CREATE FUNCTION chunks_fts_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.fts_vector := to_tsvector('english', coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_chunks_fts
BEFORE INSERT OR UPDATE OF content ON chunks
FOR EACH ROW EXECUTE FUNCTION chunks_fts_update();

-- ---------------------------------------------------------------------------
-- Row-Level Security
--
-- The FastAPI backend connects as a privileged role and enforces tenancy in
-- application code (org derived from membership, never from the client).
-- RLS is defense in depth for any direct Supabase client access
-- (anon/authenticated roles): members may READ their own orgs' data; all
-- writes go through the backend only, so no write policies are defined.
-- ---------------------------------------------------------------------------

CREATE FUNCTION is_org_member(org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM organization_members
        WHERE organization_id = org AND user_id = auth.uid()
    );
$$;

ALTER TABLE organizations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases      ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents            ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks               ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages             ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_read ON organizations FOR SELECT TO authenticated
    USING (is_org_member(id));
CREATE POLICY members_read ON organization_members FOR SELECT TO authenticated
    USING (is_org_member(organization_id));
CREATE POLICY kb_read ON knowledge_bases FOR SELECT TO authenticated
    USING (is_org_member(organization_id));
CREATE POLICY documents_read ON documents FOR SELECT TO authenticated
    USING (is_org_member(organization_id));
CREATE POLICY chunks_read ON chunks FOR SELECT TO authenticated
    USING (is_org_member(organization_id));
-- Conversations are private to their author, within an org they still belong to.
CREATE POLICY conversations_read ON conversations FOR SELECT TO authenticated
    USING (user_id = auth.uid() AND is_org_member(organization_id));
CREATE POLICY messages_read ON messages FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM conversations c
        WHERE c.id = messages.conversation_id
          AND c.user_id = auth.uid() AND is_org_member(c.organization_id)
    ));
