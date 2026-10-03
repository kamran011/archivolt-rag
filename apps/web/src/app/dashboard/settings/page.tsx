"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { OrgMember, OrgRole } from "@/lib/types";

const ROLES: OrgRole[] = ["owner", "admin", "member", "viewer"];

export default function SettingsPage() {
  const { currentOrg, refresh } = useOrganization();
  const orgId = currentOrg?.id;
  const canManage = currentOrg?.role === "owner" || currentOrg?.role === "admin";
  const isOwner = currentOrg?.role === "owner";

  const {
    data: members,
    loading,
    error: loadError,
    refresh: reloadMembers,
  } = useApiResource<OrgMember[]>(
    orgId ? `/api/v1/organizations/${orgId}/members` : null,
    orgId,
    "Failed to load members",
  );

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newUserId, setNewUserId] = useState("");
  const [newRole, setNewRole] = useState<OrgRole>("member");

  if (!currentOrg) {
    return <p className="text-sm text-gray-500">No organization selected.</p>;
  }
  const org = currentOrg;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const webSearchOn = org.settings?.web_search_enabled === true;

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Settings</h1>
      <p className="text-gray-500 text-sm mb-6">
        {org.name} · you are {org.role ?? "a member"}
      </p>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      <section className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
        <h2 className="font-medium text-gray-900 mb-1">Web search</h2>
        <p className="text-sm text-gray-500 mb-3">
          Lets members ask the assistant to supplement the knowledge base with public web results.
          Web results are always labelled external and ranked below your documents. The server
          must also have web search configured.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={webSearchOn}
            disabled={!canManage || busy}
            onChange={(e) =>
              run(async () => {
                await api.patch(
                  `/api/v1/organizations/${org.id}`,
                  { settings: { web_search_enabled: e.target.checked } },
                  org.id,
                );
                await refresh();
              })
            }
          />
          Allow web search for this organization
        </label>
        {!canManage && (
          <p className="text-xs text-gray-400 mt-2">Only owners and admins can change this.</p>
        )}
      </section>

      <section className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-medium text-gray-900 mb-3">Members</h2>
        {loadError && <p className="text-sm text-red-600 mb-2">{loadError}</p>}
        {loading ? (
          <p className="text-sm text-gray-400">Loading…</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left py-2 font-medium">User</th>
                <th className="text-left py-2 font-medium">Role</th>
                <th className="text-right py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(members ?? []).map((m) => (
                <tr key={m.id}>
                  <td className="py-2 font-mono text-xs text-gray-700">{m.user_id}</td>
                  <td className="py-2">
                    {isOwner ? (
                      <select
                        value={m.role}
                        disabled={busy}
                        onChange={(e) =>
                          run(async () => {
                            await api.patch(
                              `/api/v1/organizations/${org.id}/members/${m.id}`,
                              { role: e.target.value },
                              org.id,
                            );
                            await reloadMembers();
                          })
                        }
                        className="rounded-md border border-gray-200 px-2 py-1 text-xs"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    ) : (
                      m.role
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {canManage && (
                      <button
                        disabled={busy}
                        onClick={() => {
                          if (!window.confirm("Remove this member from the organization?")) return;
                          void run(async () => {
                            await api.delete(
                              `/api/v1/organizations/${org.id}/members/${m.id}`,
                              org.id,
                            );
                            await reloadMembers();
                          });
                        }}
                        className="cursor-pointer text-xs text-red-500 hover:text-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {canManage && (
          <form
            className="mt-4 flex flex-wrap items-end gap-2 border-t border-gray-100 pt-4"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await api.post(
                  `/api/v1/organizations/${org.id}/members`,
                  { user_id: newUserId.trim(), role: newRole },
                  org.id,
                );
                setNewUserId("");
                await reloadMembers();
              });
            }}
          >
            <label className="flex-1 min-w-64 text-xs text-gray-500">
              User ID (from Supabase Auth)
              <input
                value={newUserId}
                onChange={(e) => setNewUserId(e.target.value)}
                placeholder="00000000-0000-0000-0000-000000000000"
                className="mt-1 block w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm font-mono"
                required
              />
            </label>
            <label className="text-xs text-gray-500">
              Role
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as OrgRole)}
                className="mt-1 block rounded-md border border-gray-200 px-2 py-1.5 text-sm"
              >
                {ROLES.filter((r) => r !== "owner").map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={busy || !newUserId.trim()}
              className="cursor-pointer rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Add member
            </button>
          </form>
        )}
        {isOwner === false && canManage && (
          <p className="text-xs text-gray-400 mt-2">Only owners can change roles.</p>
        )}
      </section>
    </div>
  );
}
