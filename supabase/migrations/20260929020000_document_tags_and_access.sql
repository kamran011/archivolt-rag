-- Document metadata (tags) and document-level access control.
-- Matches backend/app/models/document.py.

ALTER TABLE documents
    ADD COLUMN tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN restricted boolean NOT NULL DEFAULT false;

CREATE INDEX ix_documents_tags ON documents USING gin (tags);
CREATE INDEX ix_documents_effective_date ON documents (effective_date);

CREATE TABLE document_access (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    CONSTRAINT uq_document_access UNIQUE (document_id, user_id)
);
CREATE INDEX ix_document_access_organization_id ON document_access (organization_id);
CREATE INDEX ix_document_access_document_id ON document_access (document_id);
CREATE INDEX ix_document_access_user_id ON document_access (user_id);

-- Direct Supabase-client reads must respect restricted documents too. The chunks and
-- documents policies from the initial migration allowed any org member; replace them.
CREATE FUNCTION can_read_document(doc_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1
        FROM documents d
        JOIN organization_members m
          ON m.organization_id = d.organization_id AND m.user_id = auth.uid()
        WHERE d.id = doc_id
          AND (
              NOT d.restricted
              OR m.role IN ('owner', 'admin')
              OR d.uploaded_by = auth.uid()
              OR EXISTS (
                  SELECT 1 FROM document_access a
                  WHERE a.document_id = d.id AND a.user_id = auth.uid()
              )
          )
    );
$$;

DROP POLICY documents_read ON documents;
CREATE POLICY documents_read ON documents FOR SELECT TO authenticated
    USING (can_read_document(id));

DROP POLICY chunks_read ON chunks;
CREATE POLICY chunks_read ON chunks FOR SELECT TO authenticated
    USING (can_read_document(document_id));

ALTER TABLE document_access ENABLE ROW LEVEL SECURITY;
-- Grants are managed through the backend; members can see only their own grants.
CREATE POLICY document_access_own ON document_access FOR SELECT TO authenticated
    USING (user_id = auth.uid());
