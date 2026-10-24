"use client";

import type { User } from "@supabase/supabase-js";
import OrgSwitcher from "@/components/layout/OrgSwitcher";
import AccountMenu from "@/components/layout/AccountMenu";

interface HeaderProps {
  user: User;
  onMenuClick?: () => void;
}

export default function Header({ user, onMenuClick }: HeaderProps) {
  return (
    <header className="h-16 bg-bg flex items-center gap-3 justify-between px-4 sm:px-6">
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
      <div className="lg:hidden">
        <AccountMenu user={user} variant="header" />
      </div>
    </header>
  );
}
