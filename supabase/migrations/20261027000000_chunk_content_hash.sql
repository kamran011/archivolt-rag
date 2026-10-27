-- Per-chunk content hash: skips re-embedding unchanged chunks on a new document
-- version and powers ingestion-time near-duplicate detection.
-- Matches backend/app/models/chunk.py.

ALTER TABLE chunks ADD COLUMN content_hash varchar(64);
CREATE INDEX ix_chunks_kb_hash ON chunks (knowledge_base_id, content_hash);
