-- Hierarchical retrieval: embedded document/section summaries (navigation aids only).
-- Matches backend/app/models/summary.py.

CREATE TABLE document_summaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    knowledge_base_id uuid NOT NULL,
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    level varchar(20) NOT NULL,
    node_id varchar(50),
    title text NOT NULL,
    summary text NOT NULL,
    embedding vector(1536),
    -- NULLS NOT DISTINCT so there is at most one document-level (node_id NULL) row
    CONSTRAINT uq_document_summary UNIQUE NULLS NOT DISTINCT (document_id, level, node_id)
);
CREATE INDEX ix_document_summaries_organization_id ON document_summaries (organization_id);
CREATE INDEX ix_document_summaries_document_id ON document_summaries (document_id);
CREATE INDEX ix_document_summaries_kb ON document_summaries (knowledge_base_id, organization_id);
CREATE INDEX ix_document_summaries_embedding_hnsw
    ON document_summaries USING hnsw (embedding vector_cosine_ops);

-- A summary is derived from its document, so it is exactly as visible as the document
-- (restricted documents included).
ALTER TABLE document_summaries ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_summaries_read ON document_summaries FOR SELECT TO authenticated
    USING (can_read_document(document_id));
