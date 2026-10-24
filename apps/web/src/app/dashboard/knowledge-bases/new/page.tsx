"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { z } from "zod";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { ApiError } from "@/lib/api";
import BackLink from "@/components/ui/BackLink";

const schema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(200),
  description: z.string().max(1000).optional(),
  chunk_strategy: z.enum(["fixed", "structure_aware"]),
  chunk_size: z.number().int().min(128, "Chunk size must be between 128 and 2048").max(2048, "Chunk size must be between 128 and 2048"),
  chunk_overlap: z.number().int().min(0, "Overlap must be between 0 and 256").max(256, "Overlap must be between 0 and 256"),
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
  const [advancedOpen, setAdvancedOpen] = useState(false);

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
      if (fieldErrors.chunk_strategy || fieldErrors.chunk_size || fieldErrors.chunk_overlap) {
        setAdvancedOpen(true);
      }
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
        <BackLink href="/dashboard/knowledge-bases" label="Knowledge Bases" />
        <h1 className="text-2xl font-semibold text-gray-900">New Knowledge Base</h1>
      </div>

      <form onSubmit={handleSubmit} className="bg-bg-white rounded-2xl border border-border p-6 space-y-5">
        {submitError && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {submitError}
          </div>
        )}

        <div>
          <label htmlFor="kb-name" className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
          <input
            id="kb-name"
            name="name"
            aria-invalid={!!errors.name}
            aria-describedby={errors.name ? "kb-name-error" : undefined}
            value={form.name}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Product Documentation"
          />
          {errors.name && <p id="kb-name-error" role="alert" className="text-red-600 text-xs mt-1">{errors.name}</p>}
        </div>

        <div>
          <label htmlFor="kb-description" className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <textarea
            id="kb-description"
            name="description"
            value={form.description}
            onChange={handleChange}
            rows={3}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            placeholder="What documents will this knowledge base contain?"
          />
        </div>

        <details
          open={advancedOpen}
          onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
          className="group"
        >
          <summary className="inline-flex min-h-10 cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 [&::-webkit-details-marker]:hidden">
            <svg
              className="h-4 w-4 transition-transform group-open:rotate-90"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
              aria-hidden
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Advanced settings
          </summary>
          <div className="mt-2 space-y-5 rounded-xl border border-border bg-bg/60 p-4">
        <p className="text-xs text-gray-500">
          These control how documents are split before search. The defaults work well for most documents.
        </p>
        <div>
          <label htmlFor="kb-chunk-strategy" className="block text-sm font-medium text-gray-700 mb-1">Chunking Strategy</label>
          <select
            id="kb-chunk-strategy"
            name="chunk_strategy"
            value={form.chunk_strategy}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="structure_aware">By headings and sections (recommended)</option>
            <option value="fixed">Fixed-size pieces</option>
          </select>
          <p className="text-gray-500 text-xs mt-1">
            {form.chunk_strategy === "structure_aware"
              ? "Splits by headings and sections. Automatically falls back to fixed-size splits when a document has no headings."
              : "Cuts every document into equal-length pieces, whatever it contains."}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="kb-chunk-size" className="block text-sm font-medium text-gray-700 mb-1">
              Chunk Size (tokens)
            </label>
            <input
              id="kb-chunk-size"
              type="number"
              name="chunk_size"
              value={form.chunk_size}
              onChange={handleChange}
              min={128}
              max={2048}
              aria-invalid={!!errors.chunk_size}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.chunk_size && <p role="alert" className="text-red-600 text-xs mt-1">{errors.chunk_size}</p>}
            <p className="text-gray-500 text-xs mt-1">
              How much text goes in each piece (512 is about 380 words). Smaller pieces match more precisely; larger ones keep more context.
            </p>
          </div>
          <div>
            <label htmlFor="kb-chunk-overlap" className="block text-sm font-medium text-gray-700 mb-1">
              Chunk Overlap (tokens)
            </label>
            <input
              id="kb-chunk-overlap"
              type="number"
              name="chunk_overlap"
              value={form.chunk_overlap}
              onChange={handleChange}
              min={0}
              max={256}
              aria-invalid={!!errors.chunk_overlap}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {errors.chunk_overlap && <p role="alert" className="text-red-600 text-xs mt-1">{errors.chunk_overlap}</p>}
            <p className="text-gray-500 text-xs mt-1">
              Text repeated between neighbouring pieces so an idea isn&apos;t cut in half (64 is about two or three sentences).
            </p>
          </div>
        </div>
          </div>
        </details>

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
