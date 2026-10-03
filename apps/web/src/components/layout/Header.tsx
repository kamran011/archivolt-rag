"use client";

import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import OrgSwitcher from "@/components/layout/OrgSwitcher";

interface HeaderProps {
  user: User;
  onMenuClick?: () => void;
}

export default function Header({ user, onMenuClick }: HeaderProps) {
  const router = useRouter();

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/auth/login");
    router.refresh();
  }

  const initials = (user.email ?? "?")
    .split("@")[0]
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center gap-3 justify-between px-4 sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label="Open navigation"
        className="cursor-pointer -ml-1 shrink-0 rounded-lg p-2 text-gray-500 hover:bg-gray-50 hover:text-gray-800 lg:hidden"
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <div className="min-w-0 flex-1">
        <OrgSwitcher />
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-500 hidden sm:inline">{user.email}</span>
        <button
          onClick={handleSignOut}
          className="text-sm font-medium text-gray-500 hover:text-gray-800 transition-colors cursor-pointer"
        >
          Sign out
        </button>
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-white text-xs font-semibold shrink-0"
          style={{ background: "linear-gradient(140deg, #c4b5fd, var(--primary))" }}
          aria-hidden
        >
          {initials}
        </div>
      </div>
    </header>
  );
}
