"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useApiResource } from "@/hooks/useApiResource";
import { useCurrentUser } from "@/hooks/useCurrentUser";
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

const STORAGE_KEY = "ragix_current_org_id";

function slugify(base: string): string {
  const cleaned = base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  // Slugs are unique across every org, not just this user's, so a random suffix avoids
  // collisions between two different people whose email local-part happens to match.
  const suffix = Math.random().toString(36).slice(2, 6);
  return `${cleaned || "workspace"}-${suffix}`;
}

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useCurrentUser();
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
  // True only while the one-time default-workspace creation below is in flight, so pages
  // show a loading state instead of a flash of "no organization" in between.
  const [provisioning, setProvisioning] = useState(false);
  const provisionedRef = useRef(false);

  function setCurrentOrgId(id: string) {
    setSelectedId(id);
    localStorage.setItem(STORAGE_KEY, id);
  }

  // Re-fetch org list (and roles) whenever the tab regains focus, so a role change
  // made in another tab or by another user propagates within seconds.
  useEffect(() => {
    const onFocus = () => { void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  // A brand-new sign-up has an auth account but no workspace yet. Create a default one
  // automatically the first time we see that, instead of making sign-up a two-step flow
  // (account, then a separate "create your workspace" page). Guarded so it only ever
  // fires once per mount and never races a concurrent load.
  useEffect(() => {
    if (loading || error || organizations.length > 0) return;
    if (!user?.email || provisionedRef.current) return;
    provisionedRef.current = true;
    setProvisioning(true);

    const localPart = user.email.split("@")[0];
    api
      .post<Organization>("/api/v1/organizations/", {
        name: `${localPart}'s workspace`,
        slug: slugify(localPart),
      })
      .then(async (org) => {
        await refresh();
        setCurrentOrgId(org.id);
      })
      .catch(() => {
        // Leave the onboarding page as a manual fallback if this ever fails
        // (e.g. a transient network error); don't retry in a loop.
      })
      .finally(() => setProvisioning(false));
  }, [loading, error, organizations.length, user?.email, refresh]);

  const currentOrg =
    organizations.find((o) => o.id === selectedId) ?? organizations[0] ?? null;

  return (
    <OrganizationContext.Provider
      value={{
        organizations,
        currentOrg,
        loading: loading || provisioning,
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
