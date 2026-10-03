"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useOrganization } from "@/providers/OrganizationProvider";

// Deliberately a neutral gray square with a building glyph, not a colored circle -
// so it never reads as a second user avatar next to the one in the header's corner.
function OrgMark() {
  return (
    <span
      className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-gray-100 text-gray-500"
      aria-hidden
    >
      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 21V5a1 1 0 011-1h10a1 1 0 011 1v16M4 21h16M4 21h0M20 21V10a1 1 0 00-1-1h-3M9 7h2M9 11h2M9 15h2" />
      </svg>
    </span>
  );
}

function ChevronIcon() {
  return (
    <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4 shrink-0 text-primary" fill="none" stroke="currentColor" strokeWidth={2.4} viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

export default function OrgSwitcher() {
  const { organizations, currentOrg, setCurrentOrgId, loading } = useOrganization();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  if (loading) return <div className="text-sm text-gray-400">Loading…</div>;

  if (!currentOrg) {
    return (
      <Link
        href="/dashboard/onboarding"
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-gray-50"
      >
        Create workspace
      </Link>
    );
  }

  const canSwitch = organizations.length > 1;

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => canSwitch && setOpen((o) => !o)}
        aria-haspopup={canSwitch ? "menu" : undefined}
        aria-expanded={canSwitch ? open : undefined}
        className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium text-gray-800 transition-colors ${
          canSwitch ? "cursor-pointer hover:bg-gray-50" : "cursor-default"
        }`}
      >
        <OrgMark />
        <span className="max-w-[160px] truncate sm:max-w-[240px]">{currentOrg.name}</span>
        {canSwitch && <ChevronIcon />}
      </button>

      {canSwitch && open && (
        <div
          role="menu"
          className="absolute left-0 top-[calc(100%+6px)] z-50 w-64 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-lg"
        >
          <p className="px-3 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            Workspaces
          </p>
          {organizations.map((org) => {
            const active = org.id === currentOrg.id;
            return (
              <button
                key={org.id}
                type="button"
                role="menuitem"
                onClick={() => {
                  setCurrentOrgId(org.id);
                  setOpen(false);
                }}
                className="flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50"
              >
                <OrgMark />
                <span className="min-w-0 flex-1 truncate font-medium text-gray-900">{org.name}</span>
                {active ? <CheckIcon /> : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
