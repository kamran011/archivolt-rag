"use client";

import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { Document, DocumentUpdate } from "@/lib/types";

export function useDocuments(kbId: string) {
  const { currentOrg } = useOrganization();
  const { data, loading, error, refresh, update } = useApiResource<Document[]>(
    currentOrg && kbId ? `/api/v1/knowledge-bases/${kbId}/documents/` : null,
    currentOrg?.id,
    "Failed to load documents",
  );
  const documents = data ?? [];

  async function uploadDocument(file: File): Promise<Document> {
    if (!currentOrg) throw new Error("No organization selected");
    const formData = new FormData();
    formData.append("file", file);
    const doc = await api.upload<Document>(
      `/api/v1/knowledge-bases/${kbId}/documents/upload`,
      formData,
      currentOrg.id
    );
    update((prev) => [doc, ...(prev ?? [])]);
    return doc;
  }

  async function deleteDocument(docId: string): Promise<void> {
    if (!currentOrg) throw new Error("No organization selected");
    await api.delete(`/api/v1/knowledge-bases/${kbId}/documents/${docId}`, currentOrg.id);
    update((prev) => (prev ?? []).filter((d) => d.id !== docId));
  }

  async function updateDocument(docId: string, patch: DocumentUpdate): Promise<Document> {
    if (!currentOrg) throw new Error("No organization selected");
    const doc = await api.patch<Document>(
      `/api/v1/knowledge-bases/${kbId}/documents/${docId}`,
      patch,
      currentOrg.id
    );
    update((prev) => (prev ?? []).map((d) => (d.id === docId ? doc : d)));
    return doc;
  }

  return { documents, loading, error, uploadDocument, deleteDocument, updateDocument, refresh };
}
