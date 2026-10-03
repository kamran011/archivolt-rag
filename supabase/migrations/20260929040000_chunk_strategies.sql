-- Semantic and agentic chunking strategies.
-- Matches ChunkStrategy in backend/app/models/knowledge_base.py.
ALTER TYPE chunkstrategy ADD VALUE IF NOT EXISTS 'semantic';
ALTER TYPE chunkstrategy ADD VALUE IF NOT EXISTS 'agentic';
