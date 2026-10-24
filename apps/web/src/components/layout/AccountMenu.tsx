"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { useOrganization } from "@/providers/OrganizationProvider";

const AVATAR_BG = "linear-gradient(140deg, #7c52ff, #5726db)";

export default function AccountMenu({
  user,
  variant,
}: {
  user: User;
  variant: "header" | "sidebar";
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const { currentOrg } = useOrganization();
  const emailPrefix = (user.email ?? "?").split("@")[0];
  const initials = emailPrefix.slice(0, 2).toUpperCase();
  const name = user.user_metadata?.full_name ?? emailPrefix;
  const role = currentOrg?.role;

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/auth/login");
    router.refresh();
  }

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const isSidebar = variant === "sidebar";

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={isSidebar ? undefined : "Account menu"}
        title={isSidebar ? `${name}${role ? ` (${role})` : ""}\n${user.email}` : undefined}
        className={
          isSidebar
            ? "flex w-full cursor-pointer items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-white/[0.06]"
            : "flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full text-xs font-semibold text-white transition-opacity hover:opacity-90"
        }
        style={isSidebar ? undefined : { background: AVATAR_BG }}
      >
        {isSidebar ? (
          <>
            <span
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
              style={{ background: AVATAR_BG }}
              aria-hidden
            >
              {initials}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 truncate">
                <span className="truncate text-sm font-medium text-white">{name}</span>
                {role && (
                  <span className="shrink-0 rounded px-1 py-0.5 text-[10px] font-medium capitalize text-white/50 bg-white/[0.08]">
                    {role}
                  </span>
                )}
              </span>
              <span className="block truncate text-xs text-white/60">{user.email}</span>
            </span>
            <svg
              className={`h-4 w-4 shrink-0 text-white/50 transition-transform ${open ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
              aria-hidden
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
            </svg>
          </>
        ) : (
          initials
        )}
      </button>

      {open && (
        <div
          className={`absolute z-50 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg ${
            isSidebar ? "bottom-[calc(100%+8px)] left-0 right-0" : "right-0 top-[calc(100%+8px)] w-64"
          }`}
        >
          {!isSidebar && (
            <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3">
              <div
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
                style={{ background: AVATAR_BG }}
                aria-hidden
              >
                {initials}
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-900">{name}</p>
                <p className="truncate text-xs text-gray-500">{user.email}</p>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={handleSignOut}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900"
          >
            <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
