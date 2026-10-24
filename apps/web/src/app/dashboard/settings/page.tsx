"use client";

import { Skeleton, SkeletonRegion } from "@/components/ui/Skeleton";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import { useCurrentUser } from "@/providers/CurrentUserProvider";
import type { OrgMember, OrgRole } from "@/lib/types";

interface OrgInvitation {
  id: string;
  email: string;
  role: OrgRole;
  created_at: string;
}

const OWNER_ASSIGNABLE: OrgRole[] = ["owner", "admin", "member", "viewer"];
const ADMIN_ASSIGNABLE: OrgRole[] = ["member", "viewer"];

export default function SettingsPage() {
  const { currentOrg, refresh } = useOrganization();
  const { user: currentUser } = useCurrentUser();
  const orgId = currentOrg?.id;
  const canManage = currentOrg?.role === "owner" || currentOrg?.role === "admin";
  const isOwner = currentOrg?.role === "owner";
  const assignableRoles = isOwner ? OWNER_ASSIGNABLE : ADMIN_ASSIGNABLE;

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

  const {
    data: invitations,
    refresh: reloadInvitations,
  } = useApiResource<OrgInvitation[]>(
    canManage && orgId ? `/api/v1/organizations/${orgId}/invitations` : null,
    orgId,
    "Failed to load invitations",
  );

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
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
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Settings</h1>
      <p className="text-gray-500 text-sm mb-6">
        {org.name} · you are {org.role ?? "a member"}
      </p>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      <section className="bg-bg-white rounded-2xl border border-border p-5 mb-6">
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
          <p className="text-xs text-gray-500 mt-2">Only owners and admins can change this.</p>
        )}
      </section>

      <section className="bg-bg-white rounded-2xl border border-border p-5">
        <h2 className="font-medium text-gray-900 mb-3">Members</h2>
        {loadError && <p role="alert" className="text-sm text-red-600 mb-2">{loadError}</p>}
        {loading ? (
          <SkeletonRegion label="Loading members" className="divide-y divide-gray-100">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center justify-between py-3">
                <Skeleton className="h-4 w-2/3 max-w-sm" />
                <Skeleton className="h-7 w-24" />
              </div>
            ))}
          </SkeletonRegion>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th scope="col" className="text-left py-2 font-medium">User</th>
                <th scope="col" className="text-left py-2 font-medium">Role</th>
                <th scope="col" className="text-right py-2 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(members ?? []).map((m) => {
                const isSelf = m.user_id === currentUser?.id;
                return (
                  <tr key={m.id}>
                    <td className="py-2 font-mono text-xs text-gray-700">
                      {m.user_id}
                      {isSelf && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                    </td>
                    <td className="py-2">
                      {canManage && !isSelf ? (
                        <select
                          value={m.role}
                          disabled={busy || !assignableRoles.includes(m.role as OrgRole)}
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
                          className="rounded-md border border-gray-200 px-2 py-1 text-xs disabled:opacity-60"
                        >
                          {assignableRoles.includes(m.role as OrgRole)
                            ? assignableRoles.map((r) => (
                                <option key={r} value={r}>
                                  {r}
                                </option>
                              ))
                            : [m.role].map((r) => (
                                <option key={r} value={r}>
                                  {r}
                                </option>
                              ))}
                        </select>
                      ) : (
                        <span className="text-xs text-gray-700">{m.role}</span>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      {canManage && !isSelf && (
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
                );
              })}
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
                  `/api/v1/organizations/${org.id}/invitations`,
                  { email: newEmail.trim(), role: newRole },
                  org.id,
                );
                setNewEmail("");
                await reloadInvitations();
              });
            }}
          >
            <label className="flex-1 min-w-64 text-xs text-gray-500">
              Invite by email
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="user@example.com"
                className="mt-1 block w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm"
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
                {assignableRoles.filter((r) => r !== "owner").map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={busy || !newEmail.trim()}
              className="cursor-pointer rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Send invite
            </button>
          </form>
        )}
        {canManage && !isOwner && (
          <p className="text-xs text-gray-500 mt-2">Admins can invite members and viewers only.</p>
        )}

        {canManage && invitations && invitations.length > 0 && (
          <div className="mt-5 border-t border-gray-100 pt-4">
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Pending invitations</h3>
            <ul className="space-y-1">
              {invitations.map((inv) => (
                <li key={inv.id} className="flex items-center justify-between text-sm">
                  <span className="text-gray-700">{inv.email}</span>
                  <span className="text-xs text-gray-400 capitalize">{inv.role} · awaiting acceptance</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
