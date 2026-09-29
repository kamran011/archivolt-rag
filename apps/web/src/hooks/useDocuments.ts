"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { Document } from "@/lib/types";

export function useDocuments(kbId: string) {
  const { currentOrg } = useOrganization();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDocuments = useCallback(async () => {
    if (!currentOrg || !kbId) {
      setDocuments([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const docs = await api.get<Document[]>(
        `/api/v1/knowledge-bases/${kbId}/documents/`,
        currentOrg.id
      );
      setDocuments(docs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [currentOrg, kbId]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  async function uploadDocument(file: File): Promise<Document> {
    if (!currentOrg) throw new Error("No organization selected");
    const formData = new FormData();
    formData.append("file", file);
    const doc = await api.upload<Document>(
      `/api/v1/knowledge-bases/${kbId}/documents/upload`,
      formData,
      currentOrg.id
    );
    setDocuments((prev) => [doc, ...prev]);
    return doc;
  }

  async function deleteDocument(docId: string): Promise<void> {
    if (!currentOrg) throw new Error("No organization selected");
    await api.delete(`/api/v1/knowledge-bases/${kbId}/documents/${docId}`, currentOrg.id);
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
  }

  return { documents, loading, error, uploadDocument, deleteDocument, refresh: fetchDocuments };
}
