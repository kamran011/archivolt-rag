"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { api } from "@/lib/api";
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
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [currentOrgId, setCurrentOrgIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const orgs = await api.get<Organization[]>("/api/v1/organizations/");
      setOrganizations(orgs);

      const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
      const validStored = stored && orgs.some((o) => o.id === stored) ? stored : null;
      const nextId = validStored ?? orgs[0]?.id ?? null;
      setCurrentOrgIdState(nextId);
      if (nextId && typeof window !== "undefined") {
        localStorage.setItem(STORAGE_KEY, nextId);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load organizations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function setCurrentOrgId(id: string) {
    setCurrentOrgIdState(id);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, id);
    }
  }

  const currentOrg = organizations.find((o) => o.id === currentOrgId) ?? null;

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
