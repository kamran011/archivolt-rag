# Groundtruth Architecture

## System Overview

Groundtruth is a production-grade AI Knowledge & Evidence Platform built around a principled RAG pipeline:

```
SOURCE
 ↓
DOCUMENT UNDERSTANDING
 ↓
DOCUMENT STRUCTURE / TREE
 ↓
MULTIPLE REPRESENTATIONS
 ↓
QUERY UNDERSTANDING
 ↓
EVIDENCE REQUIREMENTS
 ↓
ADAPTIVE RETRIEVAL
 ↓
AUTHORIZATION
 ↓
RERANKING
 ↓
EVIDENCE FILTERING
 ↓
SUFFICIENCY CHECK
 ↓
CONTEXT BUDGET
 ↓
GROUNDED GENERATION
 ↓
CLAIM VERIFICATION
 ↓
CITATIONS / ABSTENTION
```

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14+ (App Router), TypeScript, Tailwind CSS, Zod |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async |
| Database | Supabase PostgreSQL + pgvector + FTS |
| Auth | Supabase Auth |
| Storage | Supabase Storage |
| Embeddings | OpenAI text-embedding-3-small (abstracted) |
| LLM | OpenAI GPT-4o + Anthropic Claude (abstracted) |

## Repository Structure

```
groundtruth/
├── apps/
│   └── web/                 ← Next.js frontend
├── backend/                 ← Python/FastAPI backend
│   └── app/
│       ├── core/            ← DB, auth, exceptions, middleware
│       ├── models/          ← SQLAlchemy ORM interfaces
│       ├── domains/         ← Business logic by domain
│       └── providers/       ← LLM, embedding, reranker abstractions
├── supabase/
│   ├── migrations/          ← Supabase CLI-managed DB migrations
│   ├── schemas/             ← Schema documentation
│   ├── seed.sql
│   └── config.toml
└── docs/
    ├── GROUNDTRUTH_DATABASE_SPEC.md
    └── GROUNDTRUTH_ARCHITECTURE.md
```

## Implementation Phases

### Phase 1: Production RAG Foundation (current)
Auth, multi-tenancy, knowledge bases, document ingestion, hybrid search (vector + keyword + RRF), reranking, evidence gates, grounded generation with citations, abstention.

### Phase 2: Production Safety
Document versioning, freshness handling, claim verification, prompt injection protection, cross-tenant security tests, retrieval tracing.

### Phase 3: Advanced Retrieval
Document tree, hierarchical summaries, parent/child retrieval, adaptive retrieval router, evidence requirement planning.

### Phase 4: Multimodal
OCR, image/table/page representations, multimodal retrieval and citations.

### Phase 5: Agentic RAG
Bounded agents, tools (search, calculator, structured query), multi-hop retrieval.

### Phase 6: Evaluation & Optimization
Evaluation datasets, retrieval experiments, RAG triad, hallucination evaluation, cost dashboard.

## Security Model

1. Every request authenticated via Supabase JWT
2. Organization membership resolved from authenticated identity
3. All retrieval scoped by `organization_id` (application-layer enforcement)
4. Retrieved content treated as untrusted data (prompt injection protection)
5. Evidence gate prevents hallucination when context is insufficient
6. RLS policies as database-layer safety net

## Key Design Principles

- Routes never contain business logic — delegate to services
- `org_id` always derived from authenticated user, never from client input
- Retrieval always tenant-scoped — never retrieve-all-then-filter
- LLM receives only authorized, selected evidence
- Provider abstraction isolates OpenAI/Anthropic specifics
