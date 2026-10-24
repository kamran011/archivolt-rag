/**
 * Typed API client for the FastAPI backend.
 * All requests include the Supabase access token and the current organization ID.
 */
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Deduplicates concurrent GET requests to the same path+org so React StrictMode
// double-mount and rapid re-renders never send two identical network calls.
const getInFlight = new Map<string, Promise<unknown>>();

// Generic HTTP phrases that are meaningless to end users.
const GENERIC_HTTP_PHRASES = new Set([
  "not found", "internal server error", "bad request", "unauthorized",
  "forbidden", "unprocessable entity", "conflict", "service unavailable",
  "bad gateway", "gateway timeout",
]);

function friendlyMessage(status: number, backendDetail: unknown): string {
  // Use the backend detail only when it's a real custom message, not a bare HTTP phrase.
  if (typeof backendDetail === "string" && backendDetail.trim()) {
    const lower = backendDetail.trim().toLowerCase();
    if (!GENERIC_HTTP_PHRASES.has(lower)) return backendDetail.trim();
  }
  if (typeof backendDetail === "object" && backendDetail !== null && "msg" in backendDetail) {
    return String((backendDetail as Record<string, unknown>).msg);
  }
  // Fall back to friendly status-based messages.
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return "The requested resource was not found.";
  if (status === 409) return "This action conflicts with existing data.";
  if (status === 422) return "Invalid input. Please check your details and try again.";
  if (status >= 500) return "Something went wrong while processing your request. Please try again.";
  return "Something went wrong. Please try again.";
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getAuthHeaders(organizationId?: string): Promise<HeadersInit> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }

  if (organizationId) {
    headers["X-Organization-Id"] = organizationId;
  }

  return headers;
}

async function request<T>(
  path: string,
  options: RequestInit & { organizationId?: string } = {}
): Promise<T> {
  const { organizationId, ...fetchOptions } = options;
  const headers = await getAuthHeaders(organizationId);

  const response = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers: {
      ...headers,
      ...(fetchOptions.headers || {}),
    },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, friendlyMessage(response.status, detail), detail);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  get: <T>(path: string, organizationId?: string): Promise<T> => {
    const key = `${organizationId ?? ""}|${path}`;
    const existing = getInFlight.get(key) as Promise<T> | undefined;
    if (existing) return existing;
    const p = request<T>(path, { method: "GET", organizationId }).finally(() =>
      getInFlight.delete(key),
    );
    getInFlight.set(key, p);
    return p;
  },

  post: <T>(path: string, body: unknown, organizationId?: string) =>
    request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      organizationId,
    }),

  patch: <T>(path: string, body: unknown, organizationId?: string) =>
    request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
      organizationId,
    }),

  delete: <T>(path: string, organizationId?: string) =>
    request<T>(path, { method: "DELETE", organizationId }),

  /** Upload a file — uses FormData, not JSON */
  upload: async <T>(
    path: string,
    formData: FormData,
    organizationId?: string
  ): Promise<T> => {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    const headers: HeadersInit = {};
    if (session?.access_token) {
      headers["Authorization"] = `Bearer ${session.access_token}`;
    }
    if (organizationId) {
      headers["X-Organization-Id"] = organizationId;
    }

    const response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      let detail: unknown;
      try {
        detail = await response.json();
      } catch {
        detail = await response.text();
      }
      throw new ApiError(response.status, `Upload error ${response.status}`, detail);
    }
    return response.json();
  },
};

export { ApiError };
