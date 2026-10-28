"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";

export interface ConversationSummary {
  id: string;
  title: string | null;
  knowledge_base_id: string | null;
  created_at: string;
  updated_at: string;
}

export function useConversations() {
  const { currentOrg } = useOrganization();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const orgId = currentOrg?.id;

  // State is only set from the request's callbacks, so the effect below never
  // sets state synchronously; `refresh` shows the spinner for manual reloads.
  const load = useCallback(() => {
    if (!orgId) return;
    api
      .get<ConversationSummary[]>("/api/v1/chat/conversations", orgId)
      .then((data) => { setConversations(data); setError(null); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Failed to load conversations");
      })
      .finally(() => setLoading(false));
  }, [orgId]);

  const refresh = useCallback(() => {
    if (!orgId) return;
    setLoading(true);
    setError(null);
    load();
  }, [orgId, load]);

  useEffect(() => {
    load();
  }, [load]);

  return { conversations, loading, error, refresh };
}
