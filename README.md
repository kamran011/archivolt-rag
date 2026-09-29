# Archivolt — AI Knowledge & Evidence Platform

Production-grade RAG system that retrieves the right evidence, respects permissions, optimizes context, and verifies answers before they reach users.

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv)
- [Supabase CLI](https://supabase.com/docs/guides/cli)
- A Supabase project (or local via `supabase start`)

### Setup

1. **Clone and copy env files**
   ```bash
   cp .env.example .env
   cp apps/web/.env.local.example apps/web/.env.local
   ```
   Fill in your Supabase credentials.

2. **Apply database schema**
   ```bash
   supabase db push          # remote
   # or
   supabase start && supabase db reset   # local
   ```
   The schema is defined in `docs/ARCHIVOLT_DATABASE_SPEC.md` and migrations are in `supabase/migrations/`.

3. **Install and run backend**
   ```bash
   cd backend
   uv sync
   uv run uvicorn app.main:app --reload
   ```
   API available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

4. **Install and run frontend**
   ```bash
   cd apps/web
   npm install
   npm run dev
   ```
   App available at `http://localhost:3000`.

## Repository Structure

```
archivolt/
├── apps/web/           Next.js frontend (TypeScript + Tailwind)
├── backend/            FastAPI backend (Python)
│   └── app/
│       ├── core/       Database, auth, exceptions, middleware
│       ├── models/     SQLAlchemy ORM models (aligned with DB spec)
│       ├── domains/    Business logic by domain
│       └── providers/  AI provider abstractions (LLM, embeddings, reranker)
├── supabase/           Supabase CLI config and migrations
└── docs/               Architecture and database specifications
```

## Documentation

- [Architecture](docs/ARCHIVOLT_ARCHITECTURE.md)
- [Database Specification](docs/ARCHIVOLT_DATABASE_SPEC.md) *(implementation pending)*
- [API Docs](http://localhost:8000/docs) *(when running)*

## Implementation Phases

- **Phase 1 (current):** Production RAG Foundation — auth, ingestion, hybrid search, evidence gates, citations
- **Phase 2:** Production Safety — versioning, freshness, claim verification, security tests
- **Phase 3:** Advanced Retrieval — document trees, hierarchical summaries, adaptive retrieval
- **Phase 4:** Multimodal — OCR, image/table evidence
- **Phase 5:** Agentic RAG — bounded agents, tools, multi-hop
- **Phase 6:** Evaluation & Optimization — benchmarks, cost dashboard, strategy comparison
