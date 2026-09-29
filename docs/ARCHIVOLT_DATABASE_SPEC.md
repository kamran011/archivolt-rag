# Archivolt Database Specification

> **Status: PENDING**
> This document will contain the authoritative database schema for Archivolt.
> The application models in `backend/app/models/` are interface stubs that will be aligned with this spec.
> Supabase migrations in `supabase/migrations/` will implement this schema.

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
