-- Per-KB opt-in for CAG (full-context answering). Matches KnowledgeBase.cag_enabled.
ALTER TABLE knowledge_bases ADD COLUMN cag_enabled boolean NOT NULL DEFAULT false;
