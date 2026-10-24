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

  const refresh = useCallback(() => {
    if (!currentOrg) return;
    setLoading(true);
    api
      .get<ConversationSummary[]>("/api/v1/chat/conversations", currentOrg.id)
      .then(setConversations)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [currentOrg]);

  useEffect(() => {
// eslint-disable-next-line react-hooks/set-state-in-effect
        refresh();
  }, [refresh]);

  return { conversations, loading, refresh };
}
