"use client";

import { use, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import DocumentStatusBadge from "@/components/documents/DocumentStatusBadge";
import type {
  AuthorityTier,
  ChunkPage,
  Document,
  DocumentSummaries,
  DocumentTree,
  DocumentUpdate,
  TreeNode,
} from "@/lib/types";

type Tab = "overview" | "chunks" | "tree" | "summaries" | "versions";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview & access" },
  { id: "chunks", label: "Chunks" },
  { id: "tree", label: "Outline" },
  { id: "summaries", label: "Summaries" },
  { id: "versions", label: "Versions" },
];
const TIERS: AuthorityTier[] = ["official", "standard", "draft", "informal"];
const PAGE = 20;

export default function DocumentInspectorPage({
  params,
}: {
  params: Promise<{ kbId: string; docId: string }>;
}) {
  const { kbId, docId } = use(params);
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id;
  const base = `/api/v1/knowledge-bases/${kbId}/documents/${docId}`;
  const [tab, setTab] = useState<Tab>("overview");

  const doc = useApiResource<Document>(orgId ? base : null, orgId, "Failed to load document");

  return (
    <div>
      <Link
        href={`/dashboard/knowledge-bases/${kbId}`}
        className="text-sm text-gray-500 hover:text-gray-900"
      >
        ← Documents
      </Link>
      <div className="mt-2 mb-4 flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">{doc.data?.title ?? "Document"}</h1>
        {doc.data && <DocumentStatusBadge status={doc.data.status} />}
      </div>
      {doc.error && <p className="text-sm text-red-600 mb-3">{doc.error}</p>}

      <div className="flex gap-1 border-b border-gray-200 mb-5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`cursor-pointer px-3 py-2 text-sm -mb-px border-b-2 ${
              tab === t.id
                ? "border-blue-600 text-blue-700 font-medium"
                : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {doc.data && tab === "overview" && (
        <Overview
          key={doc.data.id}
          doc={doc.data}
          base={base}
          orgId={orgId!}
          canManage={currentOrg?.role === "owner" || currentOrg?.role === "admin"}
          onChanged={() => doc.refresh()}
        />
      )}
      {tab === "chunks" && <Chunks base={base} orgId={orgId} />}
      {tab === "tree" && <Outline base={base} orgId={orgId} />}
      {tab === "summaries" && <Summaries base={base} orgId={orgId} />}
      {tab === "versions" && <Versions base={base} orgId={orgId} kbId={kbId} currentId={docId} />}
    </div>
  );
}

function Overview({
  doc,
  base,
  orgId,
  canManage,
  onChanged,
}: {
  doc: Document;
  base: string;
  orgId: string;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [tags, setTags] = useState(doc.tags.join(", "));
  const [tier, setTier] = useState<AuthorityTier>(doc.authority_tier);
  const [effective, setEffective] = useState(doc.effective_date?.slice(0, 10) ?? "");
  const [restricted, setRestricted] = useState(doc.restricted);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [grantee, setGrantee] = useState("");

  const access = useApiResource<string[]>(
    canManage && doc.restricted ? `${base}/access` : null,
    orgId,
    "Failed to load access list",
  );

  async function save() {
    setSaving(true);
    setMsg(null);
    const patch: DocumentUpdate = {
      authority_tier: tier,
      tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      restricted,
      effective_date: effective ? new Date(effective).toISOString() : null,
    };
    try {
      await api.patch(base, patch, orgId);
      setMsg("Saved");
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function grant() {
    try {
      await api.post(`${base}/access`, { user_id: grantee.trim() }, orgId);
      setGrantee("");
      await access.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not grant access");
    }
  }

  async function revoke(userId: string) {
    try {
      await api.delete(`${base}/access/${userId}`, orgId);
      await access.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not revoke access");
    }
  }

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <section className="bg-bg-white rounded-2xl border border-border shadow-glow p-5 text-sm space-y-3">
        <h2 className="font-medium text-gray-900">Metadata</h2>
        <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-gray-600">
          <dt>File</dt>
          <dd>{doc.file_name}</dd>
          <dt>Type</dt>
          <dd className="uppercase">{doc.file_type}</dd>
          <dt>Pages</dt>
          <dd>{doc.page_count ?? "—"}</dd>
          <dt>Chunks</dt>
          <dd>{doc.chunk_count}</dd>
          <dt>Version</dt>
          <dd>
            v{doc.version} {doc.is_current ? "(current)" : "(superseded)"}
          </dd>
        </dl>
        {doc.error_message && <p className="text-red-600 text-xs">{doc.error_message}</p>}
      </section>

      <section className="bg-bg-white rounded-2xl border border-border shadow-glow p-5 text-sm space-y-3">
        <h2 className="font-medium text-gray-900">Governance</h2>
        <label className="block text-xs text-gray-500">
          Authority
          <select
            value={tier}
            disabled={!canManage}
            onChange={(e) => setTier(e.target.value as AuthorityTier)}
            className="mt-1 block w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm"
          >
            {TIERS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-gray-500">
          Effective from
          <input
            type="date"
            value={effective}
            disabled={!canManage}
            onChange={(e) => setEffective(e.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-gray-500">
          Tags (comma separated)
          <input
            value={tags}
            disabled={!canManage}
            onChange={(e) => setTags(e.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={restricted}
            disabled={!canManage}
            onChange={(e) => setRestricted(e.target.checked)}
          />
          Restricted — only admins and explicitly granted users can see it in search and answers
        </label>
        {canManage ? (
          <div className="flex items-center gap-3">
            <button
              onClick={() => void save()}
              disabled={saving}
              className="cursor-pointer rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Save
            </button>
            {msg && <span className="text-xs text-gray-500">{msg}</span>}
          </div>
        ) : (
          <p className="text-xs text-gray-400">Only admins can change these.</p>
        )}
      </section>

      {canManage && doc.restricted && (
        <section className="bg-bg-white rounded-2xl border border-border shadow-glow p-5 text-sm md:col-span-2">
          <h2 className="font-medium text-gray-900 mb-2">Who can read this document</h2>
          {access.error && <p className="text-xs text-red-600">{access.error}</p>}
          <ul className="divide-y divide-gray-100 mb-3">
            {(access.data ?? []).map((u) => (
              <li key={u} className="flex items-center justify-between py-1.5">
                <span className="font-mono text-xs text-gray-700">{u}</span>
                <button onClick={() => void revoke(u)} className="cursor-pointer text-xs text-red-500">
                  Revoke
                </button>
              </li>
            ))}
            {(access.data ?? []).length === 0 && (
              <li className="py-1.5 text-xs text-gray-400">Only admins can see it right now.</li>
            )}
          </ul>
          <div className="flex gap-2">
            <input
              value={grantee}
              onChange={(e) => setGrantee(e.target.value)}
              placeholder="User ID"
              className="flex-1 rounded-md border border-gray-200 px-2 py-1.5 text-sm font-mono"
            />
            <button
              onClick={() => void grant()}
              disabled={!grantee.trim()}
              className="cursor-pointer rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Grant
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function Chunks({ base, orgId }: { base: string; orgId: string | undefined }) {
  const [offset, setOffset] = useState(0);
  const page = useApiResource<ChunkPage>(
    orgId ? `${base}/chunks?limit=${PAGE}&offset=${offset}` : null,
    orgId,
    "Failed to load chunks",
  );
  const total = page.data?.total ?? 0;
  return (
    <div>
      {page.error && <p className="text-sm text-red-600 mb-2">{page.error}</p>}
      {page.loading && <p className="text-sm text-gray-400">Loading…</p>}
      <div className="rounded-2xl border border-border bg-bg-white shadow-glow p-4 space-y-3">
        {(page.data?.items ?? []).map((c) => {
          const flags = (c.metadata.injection_risk_flags as string[] | undefined) ?? [];
          const chunking = c.metadata.chunking as
            | { strategy: string; chunk_size: number; chunk_overlap: number }
            | undefined;
          return (
            <article key={c.id} className="rounded-xl border border-border p-4">
              <header className="flex flex-wrap items-center gap-2 text-xs text-gray-500 mb-2">
                <span className="font-medium text-gray-800">#{c.chunk_index}</span>
                <span>{c.token_count} tokens</span>
                {typeof c.metadata.page_number === "number" && <span>p.{c.metadata.page_number}</span>}
                <span>{c.has_embedding ? "embedded" : "no embedding"}</span>
                {chunking && (
                  <span>
                    {chunking.strategy} · {chunking.chunk_size}/{chunking.chunk_overlap}
                  </span>
                )}
                {flags.length > 0 && (
                  <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">
                    injection-like text: {flags.join(", ")}
                  </span>
                )}
              </header>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{c.content}</p>
            </article>
          );
        })}
      </div>
      <div className="mt-4 flex items-center gap-3 text-sm text-gray-500">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
          className="cursor-pointer rounded border px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Previous
        </button>
        <span>
          {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}
        </span>
        <button
          disabled={offset + PAGE >= total}
          onClick={() => setOffset(offset + PAGE)}
          className="cursor-pointer rounded border px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next
        </button>
      </div>
    </div>
  );
}

function NodeView({ node }: { node: TreeNode }) {
  return (
    <li>
      <div className="py-1 text-sm">
        <span className="text-gray-900">{node.title}</span>
        <span className="ml-2 text-xs text-gray-400">
          {node.chunk_indices.length} chunk{node.chunk_indices.length === 1 ? "" : "s"}
        </span>
      </div>
      {node.children.length > 0 && (
        <ul className="ml-4 border-l border-gray-200 pl-3">
          {node.children.map((c) => (
            <NodeView key={c.node_id} node={c} />
          ))}
        </ul>
      )}
    </li>
  );
}

function Outline({ base, orgId }: { base: string; orgId: string | undefined }) {
  const tree = useApiResource<DocumentTree>(orgId ? `${base}/tree` : null, orgId, "Failed to load outline");
  if (tree.error) return <p className="text-sm text-red-600">{tree.error}</p>;
  if (tree.loading) return <p className="text-sm text-gray-400">Loading…</p>;
  const nodes = tree.data?.nodes ?? [];
  if (nodes.length === 0) {
    return <p className="text-sm text-gray-500">This document has no heading outline.</p>;
  }
  return (
    <ul className="bg-bg-white rounded-2xl border border-border shadow-glow p-4">
      {nodes.map((n) => (
        <NodeView key={n.node_id} node={n} />
      ))}
    </ul>
  );
}

function Summaries({ base, orgId }: { base: string; orgId: string | undefined }) {
  const s = useApiResource<DocumentSummaries>(orgId ? `${base}/summaries` : null, orgId, "Failed to load summaries");
  if (s.error) return <p className="text-sm text-red-600">{s.error}</p>;
  if (s.loading) return <p className="text-sm text-gray-400">Loading…</p>;
  const items = s.data?.items ?? [];
  if (items.length === 0) return <p className="text-sm text-gray-500">No summaries were generated.</p>;
  return (
    <div className="rounded-2xl border border-border bg-bg-white shadow-glow p-4 space-y-3">
      {items.map((i) => (
        <article key={`${i.level}-${i.node_id ?? "doc"}`} className="rounded-xl border border-border p-4">
          <p className="text-xs uppercase text-gray-400 mb-1">{i.level}</p>
          <h3 className="text-sm font-medium text-gray-900">{i.title}</h3>
          <p className="text-sm text-gray-600 mt-1">{i.summary}</p>
        </article>
      ))}
    </div>
  );
}

function Versions({
  base,
  orgId,
  kbId,
  currentId,
}: {
  base: string;
  orgId: string | undefined;
  kbId: string;
  currentId: string;
}) {
  const v = useApiResource<Document[]>(orgId ? `${base}/versions` : null, orgId, "Failed to load versions");
  if (v.error) return <p className="text-sm text-red-600">{v.error}</p>;
  if (v.loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <ul className="bg-bg-white rounded-2xl border border-border shadow-glow divide-y divide-gray-100">
      {(v.data ?? []).map((d) => (
        <li key={d.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
          <span>
            v{d.version} · {d.file_name}
            {d.is_current && <span className="ml-2 rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-700">current</span>}
          </span>
          <span className="flex items-center gap-4 text-xs text-gray-500">
            {new Date(d.created_at).toLocaleDateString()}
            {d.id === currentId ? (
              "viewing"
            ) : (
              <Link className="text-blue-600" href={`/dashboard/knowledge-bases/${kbId}/documents/${d.id}`}>
                Open
              </Link>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
