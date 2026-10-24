"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
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

const STORAGE_KEY = "ragix_current_org_id";

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
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

  // Send a user with no workspace to onboarding the first time they land in the app.
  useEffect(() => {
    if (!loading && organizations.length === 0 && !pathname.startsWith("/dashboard/onboarding")) {
      router.replace("/dashboard/onboarding");
    }
  }, [loading, organizations.length, pathname, router]);

  // Re-fetch org list (and roles) whenever the tab regains focus, throttled
  // to at most once every 30 s to avoid cascading re-fetches in child hooks.
  useEffect(() => {
    let lastFetch = 0;
    const onFocus = () => {
      const now = Date.now();
      if (now - lastFetch < 30_000) return;
      lastFetch = now;
      void refresh();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const currentOrg =
    organizations.find((o) => o.id === selectedId) ?? organizations[0] ?? null;

  return (
    <OrganizationContext.Provider
      value={{
        organizations,
        currentOrg,
        loading,
        error,
        setCurrentOrgId,
        refresh,
      }}
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
