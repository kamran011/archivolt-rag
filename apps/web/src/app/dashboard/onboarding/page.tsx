"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { api, ApiError } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { Organization } from "@/lib/types";

const schema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(200),
  slug: z
    .string()
    .min(2)
    .max(100)
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, numbers, and hyphens only"),
});

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function OnboardingPage() {
  const router = useRouter();
  const { refresh, setCurrentOrgId } = useOrganization();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleNameChange(value: string) {
    setName(value);
    if (!slugEdited) setSlug(slugify(value));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setSubmitError(null);

    const result = schema.safeParse({ name, slug });
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
      const org = await api.post<Organization>("/api/v1/organizations/", result.data);
      await refresh();
      setCurrentOrgId(org.id);
      router.push("/dashboard");
    } catch (e) {
      setSubmitError(
        e instanceof ApiError ? String(e.detail ?? e.message) : "Failed to create organization"
      );
      setLoading(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto mt-12">
      <div className="text-center mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Create your workspace</h1>
        <p className="text-gray-500 text-sm mt-1">
          Organizations keep your knowledge bases and team isolated from other workspaces.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="bg-bg-white rounded-2xl border border-border shadow-glow p-6 space-y-5">
        {submitError && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {submitError}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Organization name</label>
          <input
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Acme Inc."
          />
          {errors.name && <p className="text-red-600 text-xs mt-1">{errors.name}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Slug</label>
          <input
            value={slug}
            onChange={(e) => {
              setSlugEdited(true);
              setSlug(e.target.value);
            }}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="acme-inc"
          />
          {errors.slug && <p className="text-red-600 text-xs mt-1">{errors.slug}</p>}
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full cursor-pointer rounded-lg bg-blue-600 text-white py-2.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </div>
  );
}
