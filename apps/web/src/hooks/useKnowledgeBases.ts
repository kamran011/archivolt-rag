"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
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
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchKBs = useCallback(async () => {
    if (!currentOrg) {
      setKnowledgeBases([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const kbs = await api.get<KnowledgeBase[]>(
        "/api/v1/knowledge-bases/",
        currentOrg.id
      );
      setKnowledgeBases(kbs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load knowledge bases");
    } finally {
      setLoading(false);
    }
  }, [currentOrg]);

  useEffect(() => {
    fetchKBs();
  }, [fetchKBs]);

  async function createKB(input: CreateKBInput): Promise<KnowledgeBase> {
    if (!currentOrg) throw new Error("No organization selected");
    const kb = await api.post<KnowledgeBase>(
      "/api/v1/knowledge-bases/",
      input,
      currentOrg.id
    );
    setKnowledgeBases((prev) => [kb, ...prev]);
    return kb;
  }

  return { knowledgeBases, loading, error, createKB, refresh: fetchKBs };
}
