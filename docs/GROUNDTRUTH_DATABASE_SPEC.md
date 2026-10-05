# Groundtruth Database Specification

> **Status: DERIVED (interim)**
> No authoritative spec has been supplied yet. The schema in
> `supabase/migrations/20260929000000_initial_schema.sql` was derived from the
> SQLAlchemy models in `backend/app/models/`, and adds the search indexes, the
> `fts_vector` trigger and read-only RLS policies. If an authoritative spec
> differs, reconcile with a follow-up migration.
>
> Verified by applying the migration to the `supabase/postgres:15.8.1.085`
> image (pgvector, `auth.uid()`, `authenticated` role): the HNSW index is used
> for cosine search, FTS matches via the trigger, and RLS hides other orgs'
> rows and blocks direct writes. The full `supabase start` stack was not run.

## Overview

The database schema supports:
- Multi-tenant organizations with RBAC
- Knowledge bases and document management
- Document parsing, chunking, and embedding storage
- Vector similarity search (pgvector) and full-text search
- RAG pipeline state tracking (conversations, messages, citations)
- Evaluation and observability data

## Required PostgreSQL Extensions

- `vector` (pgvector) — vector similarity search
- `pg_trgm` — trigram similarity for fuzzy text search
- `pgcrypto` — UUID generation

## Tables

<!-- Database tables and schema will be defined here -->
<!-- When this spec is provided, update backend/app/models/ to match exactly -->

## Indexes

<!-- Performance indexes, HNSW, GIN indexes to be defined here -->

## RLS Policies

<!-- Row-Level Security policies for Supabase client access -->

## Migrations

All migrations are managed by the Supabase CLI and live in `supabase/migrations/`.
To apply: `supabase db push` (remote) or `supabase db reset` (local).
