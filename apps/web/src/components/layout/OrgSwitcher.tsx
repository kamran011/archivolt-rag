"use client";

import Link from "next/link";
import { useOrganization } from "@/providers/OrganizationProvider";

export default function OrgSwitcher() {
  const { organizations, currentOrg, setCurrentOrgId, loading } = useOrganization();

  if (loading) return <div className="text-sm text-gray-400">Loading…</div>;

  if (!currentOrg) {
    return (
      <Link href="/dashboard/onboarding" className="text-sm text-blue-600 hover:underline">
        Create workspace
      </Link>
    );
  }

  if (organizations.length === 1) {
    return <span className="text-sm font-medium text-gray-700">{currentOrg.name}</span>;
  }

  return (
    <select
      value={currentOrg.id}
      onChange={(e) => setCurrentOrgId(e.target.value)}
      className="text-sm font-medium text-gray-700 bg-transparent border-none focus:outline-none cursor-pointer"
    >
      {organizations.map((org) => (
        <option key={org.id} value={org.id}>
          {org.name}
        </option>
      ))}
    </select>
  );
}
