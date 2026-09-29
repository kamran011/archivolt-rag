-- Rows of tabular documents (CSV / JSON record lists) for the structured_query tool.
-- Matches backend/app/models/document_row.py.

CREATE TABLE document_rows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    knowledge_base_id uuid NOT NULL,
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    row_index integer NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX ix_document_rows_organization_id ON document_rows (organization_id);
CREATE INDEX ix_document_rows_doc_row ON document_rows (document_id, row_index);

-- Rows are document content: exactly as visible as the document itself.
ALTER TABLE document_rows ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_rows_read ON document_rows FOR SELECT TO authenticated
    USING (can_read_document(document_id));
