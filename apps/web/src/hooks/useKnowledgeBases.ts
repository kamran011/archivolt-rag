"use client";

import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { ChunkStrategy, KnowledgeBase } from "@/lib/types";

interface CreateKBInput {
  name: string;
  description?: string;
  chunk_strategy: ChunkStrategy;
  chunk_size: number;
  chunk_overlap: number;
}

export function useKnowledgeBases() {
  const { currentOrg } = useOrganization();
  const { data, loading, error, refresh, update } = useApiResource<KnowledgeBase[]>(
    currentOrg ? "/api/v1/knowledge-bases/" : null,
    currentOrg?.id,
    "Failed to load knowledge bases",
  );

  async function createKB(input: CreateKBInput): Promise<KnowledgeBase> {
    if (!currentOrg) throw new Error("No organization selected");
    const kb = await api.post<KnowledgeBase>("/api/v1/knowledge-bases/", input, currentOrg.id);
    update((prev) => [kb, ...(prev ?? [])]);
    return kb;
  }

  return { knowledgeBases: data ?? [], loading, error, createKB, refresh };
}
