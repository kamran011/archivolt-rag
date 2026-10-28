"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import AccountMenu from "@/components/layout/AccountMenu";
import { useConversations } from "@/hooks/useConversations";
import { useOrganization } from "@/providers/OrganizationProvider";

const NAV_ITEMS = [
  {
    label: "Dashboard",
    href: "/dashboard",
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    label: "Knowledge Bases",
    href: "/dashboard/knowledge-bases",
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
  {
    label: "Analytics",
    href: "/dashboard/analytics",
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
  },
  {
    label: "Retrieval Debugger",
    href: "/dashboard/debug",
    adminOnly: true,
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    label: "Evaluation Lab",
    href: "/dashboard/evals",
    adminOnly: true,
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    label: "Escalations",
    href: "/dashboard/escalations",
    adminOnly: true,
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z" />
      </svg>
    ),
  },
  {
    label: "Architecture",
    href: "/dashboard/architecture",
    adminOnly: true,
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
      </svg>
    ),
  },
  {
    label: "Settings",
    href: "/dashboard/settings",
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
];

const CHAT_ICON = (
  <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
  </svg>
);

const NEW_CHAT_ICON = (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
  </svg>
);

type NavItem = { label: string; href: string; icon: React.ReactNode; adminOnly?: boolean };

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm transition-colors cursor-pointer ${
        active
          ? "bg-white/[0.06] text-[#c4b5fd] font-semibold"
          : "text-white/60 font-medium hover:bg-white/[0.06] hover:text-white"
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 h-[22px] w-[3px] rounded-r-full bg-[#a78bfa]" />
      )}
      <span className={active ? "text-[#a78bfa]" : ""}>{item.icon}</span>
      {item.label}
    </Link>
  );
}

export default function Sidebar({
  user,
  open = false,
  onClose,
}: {
  user: User;
  open?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { conversations, error: conversationsError } = useConversations();
  const { currentOrg } = useOrganization();
  const isAdmin = currentOrg?.role === "owner" || currentOrg?.role === "admin";
  const navItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

  const chatActive = pathname.startsWith("/dashboard/chat");

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => {
    onClose?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="fixed inset-0 z-30 cursor-default bg-black/30 lg:hidden"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 shrink-0 bg-[#0d0a1f] border-r border-white/[0.08] flex flex-col transition-[transform,visibility] duration-200 ease-out lg:visible lg:static lg:translate-x-0 ${
          open ? "visible translate-x-0" : "invisible -translate-x-full"
        }`}
      >
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-white/[0.08]">
          <svg width="24" height="24" viewBox="0 0 32 32" fill="none" className="shrink-0" aria-hidden>
            <rect x="4" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55"/>
            <rect x="4" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4"/>
            <rect x="4" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25"/>
            <polygon points="20,5 24,16.5 21.2,16.5 24,26 16,16.5 19,16.5" fill="#a78bfa"/>
            <circle cx="12.5" cy="11.5" r="3.2" fill="none" stroke="#a78bfa" strokeWidth="1.8"/>
            <line x1="14.8" y1="13.8" x2="17.5" y2="16.5" stroke="#a78bfa" strokeWidth="1.8" strokeLinecap="round"/>
          </svg>
          <span className="text-lg font-bold text-white tracking-tight flex-1">Ragix</span>
          <button
            type="button"
            aria-label="Close navigation"
            onClick={onClose}
            className="cursor-pointer rounded-lg p-1.5 text-white/50 hover:bg-white/[0.06] hover:text-white lg:hidden"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <nav aria-label="Main" className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {/* Nav items above Chat */}
          {navItems.slice(0, 2).map((item) => {
            const active =
              item.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.href);
            return <NavLink key={item.href} item={item} active={active} />;
          })}

          {/* Chat section with conversation history */}
          <div>
            <div className="flex items-center gap-1">
              <Link
                href="/dashboard/chat"
                aria-current={chatActive ? "page" : undefined}
                className={`relative flex flex-1 items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm transition-colors cursor-pointer ${
                  chatActive
                    ? "bg-white/[0.06] text-[#c4b5fd] font-semibold"
                    : "text-white/60 font-medium hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                {chatActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 h-[22px] w-[3px] rounded-r-full bg-[#a78bfa]" />
                )}
                <span className={chatActive ? "text-[#a78bfa]" : ""}>{CHAT_ICON}</span>
                Chat
              </Link>
              <button
                type="button"
                onClick={() => router.push("/dashboard/chat")}
                aria-label="New conversation"
                className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg text-white/50 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-[#a78bfa]"
              >
                {NEW_CHAT_ICON}
              </button>
            </div>

            {/* Recent conversations */}
            {conversationsError && (
              <p className="ml-5 mt-1 truncate pl-3 text-[11px] text-red-400/80">
                {conversationsError}
              </p>
            )}
            {conversations.length > 0 && (
              <ul className="ml-5 mt-0.5 space-y-0.5 border-l border-white/[0.1] pl-3">
                {conversations.slice(0, 12).map((conv) => {
                  const href = `/dashboard/chat/${conv.id}`;
                  const active = pathname === href;
                  return (
                    <li key={conv.id}>
                      <Link
                        href={href}
                        aria-current={active ? "page" : undefined}
                        title={conv.title ?? "Untitled conversation"}
                        className={`block truncate rounded-lg px-2.5 py-1.5 text-xs transition-colors cursor-pointer ${
                          active
                            ? "bg-white/[0.06] font-semibold text-[#c4b5fd]"
                            : "text-white/55 hover:bg-white/[0.06] hover:text-white"
                        }`}
                      >
                        {conv.title ?? "Untitled conversation"}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Remaining nav items */}
          {navItems.slice(2).map((item) => {
            const active = pathname.startsWith(item.href);
            return <NavLink key={item.href} item={item} active={active} />;
          })}
        </nav>

        <div className="hidden border-t border-white/[0.08] p-3 lg:block">
          <AccountMenu user={user} variant="sidebar" />
        </div>
      </aside>
    </>
  );
}
