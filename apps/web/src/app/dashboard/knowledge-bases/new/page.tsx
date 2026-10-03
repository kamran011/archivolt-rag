"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { z } from "zod";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { ApiError } from "@/lib/api";

const schema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(200),
  description: z.string().max(1000).optional(),
  chunk_strategy: z.enum(["fixed", "structure_aware"]),
  chunk_size: z.number().int().min(128).max(2048),
  chunk_overlap: z.number().int().min(0).max(256),
});

export default function NewKnowledgeBasePage() {
  const router = useRouter();
  const { createKB } = useKnowledgeBases();
  const [form, setForm] = useState({
    name: "",
    description: "",
    chunk_strategy: "structure_aware" as "fixed" | "structure_aware",
    chunk_size: 512,
    chunk_overlap: 64,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) {
    const { name, value, type } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: type === "number" ? parseInt(value) : value,
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setSubmitError(null);

    const result = schema.safeParse(form);
    if (!result.success) {
      const fieldErrors: Record<string, string> = {};
      result.error.issues.forEach((issue) => {
        fieldErrors[String(issue.path[0])] = issue.message;
      });
      setErrors(fieldErrors);
      return;
    }

    setLoading(true);
    try {
      const kb = await createKB(result.data);
      router.push(`/dashboard/knowledge-bases/${kb.id}`);
    } catch (e) {
      setSubmitError(
        e instanceof ApiError ? String(e.detail ?? e.message) : "Failed to create knowledge base"
      );
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <Link href="/dashboard/knowledge-bases" className="text-sm text-gray-500 hover:text-gray-900">
          ← Knowledge Bases
        </Link>
        <h1 className="text-2xl font-semibold text-gray-900 mt-2">New Knowledge Base</h1>
      </div>

      <form onSubmit={handleSubmit} className="bg-bg-white rounded-2xl border border-border shadow-glow p-6 space-y-5">
        {submitError && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {submitError}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
          <input
            name="name"
            value={form.name}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Product Documentation"
          />
          {errors.name && <p className="text-red-600 text-xs mt-1">{errors.name}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <textarea
            name="description"
            value={form.description}
            onChange={handleChange}
            rows={3}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            placeholder="What documents will this knowledge base contain?"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Chunking Strategy</label>
          <select
            name="chunk_strategy"
            value={form.chunk_strategy}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="structure_aware">Structure-Aware (recommended)</option>
            <option value="fixed">Fixed Size</option>
          </select>
          <p className="text-gray-400 text-xs mt-1">
            Structure-aware preserves headings and sections. Fixed splits by token count.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Chunk Size (tokens)
            </label>
            <input
              type="number"
              name="chunk_size"
              value={form.chunk_size}
              onChange={handleChange}
              min={128}
              max={2048}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Chunk Overlap (tokens)
            </label>
            <input
              type="number"
              name="chunk_overlap"
              value={form.chunk_overlap}
              onChange={handleChange}
              min={0}
              max={256}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <Link
            href="/dashboard/knowledge-bases"
            className="rounded-lg border border-gray-300 text-gray-700 px-4 py-2 text-sm hover:bg-gray-50 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={loading}
            className="cursor-pointer rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Creating…" : "Create knowledge base"}
          </button>
        </div>
      </form>
    </div>
  );
}
