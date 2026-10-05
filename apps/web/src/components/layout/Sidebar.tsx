"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useConversations } from "@/hooks/useConversations";

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
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    label: "Evaluation Lab",
    href: "/dashboard/evals",
    icon: (
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    label: "Architecture",
    href: "/dashboard/architecture",
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

type NavItem = { label: string; href: string; icon: React.ReactNode };

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={`relative flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm transition-colors cursor-pointer ${
        active
          ? "text-primary font-semibold"
          : "text-gray-500 font-medium hover:bg-gray-50 hover:text-gray-800"
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 h-[22px] w-[3px] rounded-r-full bg-primary" />
      )}
      <span className={active ? "text-primary" : ""}>{item.icon}</span>
      {item.label}
    </Link>
  );
}

export default function Sidebar({
  open = false,
  onClose,
}: {
  open?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { conversations } = useConversations();

  const chatActive = pathname.startsWith("/dashboard/chat");

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
        className={`fixed inset-y-0 left-0 z-40 w-64 shrink-0 bg-bg flex flex-col transition-transform duration-200 ease-out lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-gray-100">
          <svg width="24" height="24" viewBox="0 0 28 28" fill="none" className="shrink-0">
            <circle cx="14" cy="14" r="5" stroke="var(--primary)" strokeWidth="2.2" />
            <circle cx="14" cy="14" r="9.5" stroke="var(--primary)" strokeWidth="2" opacity="0.55" />
            <circle cx="14" cy="14" r="13" stroke="var(--primary)" strokeWidth="1.6" opacity="0.3" />
          </svg>
          <span className="text-lg font-bold text-gray-900 tracking-tight flex-1">Groundtruth</span>
          <button
            type="button"
            aria-label="Close navigation"
            onClick={onClose}
            className="cursor-pointer rounded-lg p-1.5 text-gray-400 hover:bg-gray-50 hover:text-gray-700 lg:hidden"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {/* Nav items above Chat */}
          {NAV_ITEMS.slice(0, 2).map((item) => {
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
                className={`relative flex flex-1 items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm transition-colors cursor-pointer ${
                  chatActive
                    ? "text-primary font-semibold"
                    : "text-gray-500 font-medium hover:bg-gray-50 hover:text-gray-800"
                }`}
              >
                {chatActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 h-[22px] w-[3px] rounded-r-full bg-primary" />
                )}
                <span className={chatActive ? "text-primary" : ""}>{CHAT_ICON}</span>
                Chat
              </Link>
              <button
                type="button"
                onClick={() => router.push("/dashboard/chat")}
                aria-label="New conversation"
                className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-50 hover:text-gray-700 focus-visible:outline-2 focus-visible:outline-primary"
              >
                {NEW_CHAT_ICON}
              </button>
            </div>

            {/* Recent conversations */}
            {conversations.length > 0 && (
              <ul className="ml-5 mt-0.5 space-y-0.5 border-l border-gray-200 pl-3">
                {conversations.slice(0, 12).map((conv) => {
                  const href = `/dashboard/chat/${conv.id}`;
                  const active = pathname === href;
                  return (
                    <li key={conv.id}>
                      <Link
                        href={href}
                        title={conv.title ?? "Untitled conversation"}
                        className={`block truncate rounded-lg px-2.5 py-1.5 text-xs transition-colors cursor-pointer ${
                          active
                            ? "bg-gray-50 font-semibold text-primary"
                            : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"
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
          {NAV_ITEMS.slice(2).map((item) => {
            const active = pathname.startsWith(item.href);
            return <NavLink key={item.href} item={item} active={active} />;
          })}
        </nav>
      </aside>
    </>
  );
}
