"use client";

import { Skeleton, SkeletonRegion } from "@/components/ui/Skeleton";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import { useCurrentUser } from "@/providers/CurrentUserProvider";
import type { EscalationSettings, OrgMember, OrgRole } from "@/lib/types";

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

  const {
    data: escSettings,
    refresh: reloadEsc,
  } = useApiResource<EscalationSettings>(
    canManage && orgId ? `/api/v1/escalations/settings` : null,
    orgId,
    "Failed to load handoff settings",
  );
  const [escDraft, setEscDraft] = useState<EscalationSettings | null>(null);

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

  const defaultEsc: EscalationSettings = {
    enabled: false,
    triggers: ["user_request", "frustration", "abstain"],
    emails: [],
    slack_webhook_url: null,
    customer_message: "Your question has been forwarded to our support team. Someone will be in touch shortly.",
  };

  const esc = escDraft ?? escSettings ?? defaultEsc;

  async function saveEsc() {
    await run(async () => {
      await api.put(`/api/v1/escalations/settings`, esc, org.id);
      setEscDraft(null);
      await reloadEsc();
    });
  }

  return (
    <div>
      {busy && (
        <div className="skeleton fixed top-0 left-0 right-0 h-0.5 z-50" aria-hidden />
      )}
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Settings</h1>
      <p className="text-gray-500 text-sm mb-6">
        {org.name} · you are {org.role ?? "a member"}
      </p>

      {error && (
        <div role="alert" className="flex items-start justify-between gap-3 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            aria-label="Dismiss error"
            className="cursor-pointer shrink-0 text-red-400 hover:text-red-600"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>
      )}

      <section className={`relative bg-bg-white rounded-2xl border border-border p-5 mb-6 transition-opacity duration-200 ${busy ? "opacity-60 pointer-events-none" : ""}`}>
        {busy && <div className="skeleton absolute inset-0 rounded-2xl opacity-30" aria-hidden />}
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

      <section className={`relative bg-bg-white rounded-2xl border border-border p-5 transition-opacity duration-200 ${busy ? "opacity-60 pointer-events-none" : ""}`}>
        {busy && <div className="skeleton absolute inset-0 rounded-2xl opacity-30" aria-hidden />}
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
              {busy ? "Sending…" : "Send invite"}
            </button>
          </form>
        )}
        {canManage && !isOwner && (
          <p className="text-xs text-gray-500 mt-2">Admins can invite members and viewers only.</p>
        )}

        {canManage && invitations && invitations.length > 0 && (
          <div className="mt-5 border-t border-gray-100 pt-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">Pending invitations</h3>
              <span className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-xs font-medium text-amber-700">
                {invitations.length} awaiting
              </span>
            </div>
            <ul className="space-y-2">
              {invitations.map((inv) => (
                <li key={inv.id} className="flex items-center justify-between gap-3 rounded-xl border border-gray-100 bg-gray-50/60 px-3 py-2.5">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-600">
                      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm text-gray-800 truncate">{inv.email}</p>
                      <p className="text-xs text-gray-400 capitalize">{inv.role} · awaiting acceptance</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await api.post(
                            `/api/v1/organizations/${org.id}/invitations/${inv.id}/resend`,
                            {},
                            org.id,
                          );
                        })
                      }
                      className="cursor-pointer flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 hover:border-primary hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Resend invitation email"
                    >
                      <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      Resend
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        if (!window.confirm(`Revoke invitation for ${inv.email}?`)) return;
                        void run(async () => {
                          await api.delete(
                            `/api/v1/organizations/${org.id}/invitations/${inv.id}`,
                            org.id,
                          );
                          await reloadInvitations();
                        });
                      }}
                      className="cursor-pointer flex items-center gap-1 rounded-md border border-transparent px-2 py-1 text-xs text-gray-400 hover:border-red-200 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Revoke invitation"
                    >
                      <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                      Revoke
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {canManage && (
        <section className={`relative bg-bg-white rounded-2xl border border-border p-5 mt-6 transition-opacity duration-200 ${busy ? "opacity-60 pointer-events-none" : ""}`}>
          {busy && <div className="skeleton absolute inset-0 rounded-2xl opacity-30" aria-hidden />}
          <h2 className="font-medium text-gray-900 mb-1">Human handoff</h2>
          <p className="text-sm text-gray-500 mb-4">
            When a customer asks for a human, sounds frustrated, or receives an abstained answer,
            the conversation can be escalated. Admins receive a notification and can resolve the
            escalation from the Escalations page.
          </p>

          <label className="flex items-center gap-2 text-sm mb-4">
            <input
              type="checkbox"
              checked={esc.enabled}
              disabled={busy}
              onChange={(e) => setEscDraft({ ...esc, enabled: e.target.checked })}
            />
            Enable human handoff for this organization
          </label>

          {esc.enabled && (
            <div className="space-y-4">
              <fieldset>
                <legend className="text-xs font-medium text-gray-700 mb-2">Trigger conditions</legend>
                <div className="flex flex-wrap gap-4">
                  {(["user_request", "frustration", "abstain"] as const).map((t) => (
                    <label key={t} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={esc.triggers.includes(t)}
                        disabled={busy}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...esc.triggers, t]
                            : esc.triggers.filter((x) => x !== t);
                          setEscDraft({ ...esc, triggers: next });
                        }}
                      />
                      {t === "user_request" ? "Customer asks for a human" : t === "frustration" ? "Customer sounds frustrated" : "Abstained answer"}
                    </label>
                  ))}
                </div>
              </fieldset>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Notification emails <span className="text-gray-400 font-normal">(one per line)</span>
                </label>
                <textarea
                  rows={3}
                  value={esc.emails.join("\n")}
                  disabled={busy}
                  onChange={(e) =>
                    setEscDraft({
                      ...esc,
                      emails: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                    })
                  }
                  placeholder="admin@example.com"
                  className="block w-full rounded-md border border-gray-200 px-3 py-2 text-sm font-mono resize-none disabled:opacity-60"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Slack webhook URL <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  type="url"
                  value={esc.slack_webhook_url ?? ""}
                  disabled={busy}
                  onChange={(e) => setEscDraft({ ...esc, slack_webhook_url: e.target.value || null })}
                  placeholder="https://hooks.slack.com/services/..."
                  className="block w-full rounded-md border border-gray-200 px-3 py-2 text-sm disabled:opacity-60"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  Message shown to the customer when escalated
                </label>
                <textarea
                  rows={3}
                  value={esc.customer_message}
                  disabled={busy}
                  onChange={(e) => setEscDraft({ ...esc, customer_message: e.target.value })}
                  className="block w-full rounded-md border border-gray-200 px-3 py-2 text-sm resize-none disabled:opacity-60"
                />
              </div>
            </div>
          )}

          <div className="mt-4 flex justify-end">
            <button
              disabled={busy}
              onClick={() => void saveEsc()}
              className="cursor-pointer rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Save handoff settings
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
