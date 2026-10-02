"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface State<T> {
  key: string;
  scope: string;
  data: T | null;
  error: string | null;
}

/**
 * GET a resource and keep it in state. State is only set after the request settles
 * (never synchronously inside the effect), and a result for a stale key is ignored,
 * so switching org/path can neither flash old data nor race. `path === null` means
 * "nothing to load".
 */
export function useApiResource<T>(
  path: string | null,
  orgId: string | undefined,
  errorMessage: string,
) {
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<State<T>>({ key: "", scope: "", data: null, error: null });
  const scope = `${orgId ?? ""}|${path ?? ""}`;
  const key = `${scope}|${reload}`;

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    api
      .get<T>(path, orgId)
      .then((data) => {
        if (!cancelled) setState({ key, scope, data, error: null });
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setState({ key, scope, data: null, error: e instanceof Error ? e.message : errorMessage });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key, scope, path, orgId, errorMessage]);

  const refresh = useCallback(async () => setReload((n) => n + 1), []);
  const update = useCallback(
    (fn: (prev: T | null) => T | null) =>
      setState((s) => ({ ...s, data: fn(s.data) })),
    [],
  );

  const settled = state.key === key;
  return {
    // keep the previous data while reloading the same resource, never another org's
    data: state.scope === scope ? state.data : null,
    loading: path !== null && !settled,
    error: settled ? state.error : null,
    refresh,
    update,
  };
}
