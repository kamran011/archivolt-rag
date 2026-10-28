-- Duplicate-upload guard: hash of the raw uploaded bytes, checked before storing a new
-- document or version. Matches backend/app/models/document.py.

ALTER TABLE documents ADD COLUMN file_hash varchar(64);
CREATE INDEX ix_documents_kb_file_hash ON documents (knowledge_base_id, file_hash);
