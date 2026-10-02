"use client";

import { createContext, useContext, useState } from "react";
import { useApiResource } from "@/hooks/useApiResource";
import type { Organization } from "@/lib/types";

interface OrganizationContextValue {
  organizations: Organization[];
  currentOrg: Organization | null;
  loading: boolean;
  error: string | null;
  setCurrentOrgId: (id: string) => void;
  refresh: () => Promise<void>;
}

const OrganizationContext = createContext<OrganizationContextValue | null>(null);

const STORAGE_KEY = "archivolt_current_org_id";

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const { data, loading, error, refresh } = useApiResource<Organization[]>(
    "/api/v1/organizations/",
    undefined,
    "Failed to load organizations",
  );
  const organizations = data ?? [];
  // The remembered choice is read once, lazily; it only matters after organizations load.
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null,
  );

  function setCurrentOrgId(id: string) {
    setSelectedId(id);
    localStorage.setItem(STORAGE_KEY, id);
  }

  const currentOrg =
    organizations.find((o) => o.id === selectedId) ?? organizations[0] ?? null;

  return (
    <OrganizationContext.Provider
      value={{ organizations, currentOrg, loading, error, setCurrentOrgId, refresh }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}

export function useOrganization() {
  const ctx = useContext(OrganizationContext);
  if (!ctx) {
    throw new Error("useOrganization must be used within OrganizationProvider");
  }
  return ctx;
}
