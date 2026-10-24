"use client";

import type { ReactNode } from "react";

const LOGO = (
  <svg width="48" height="48" viewBox="0 0 32 32" fill="none" aria-hidden>
    <rect width="32" height="32" rx="7" fill="white" fillOpacity="0.08" />
    <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55" />
    <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4" />
    <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25" />
    <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa" />
    <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5" />
    <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const FEATURES = [
  {
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
    text: "Hybrid search across all your documents",
  },
  {
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
    text: "Every answer cited and verified against sources",
  },
  {
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    text: "Role-based access control for your team",
  },
];

export default function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      {/* Left panel — brand */}
      <div
        className="hidden lg:flex lg:w-[45%] xl:w-[40%] flex-col justify-between p-12"
        style={{
          background: "radial-gradient(ellipse at 30% 50%, #1e1240 0%, #0d0a1f 60%)",
        }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3">
          {LOGO}
          <span className="text-xl font-bold text-white tracking-tight">Ragix</span>
        </div>

        {/* Center copy */}
        <div>
          <h2 className="text-3xl font-bold text-white leading-snug mb-4">
            Ask questions.<br />
            Get answers.<br />
            <span className="text-[#a78bfa]">Cite sources.</span>
          </h2>
          <p className="text-white/50 text-sm leading-relaxed mb-10">
            Connect your knowledge base and let your team get accurate,
            evidence-backed answers, instantly.
          </p>

          <ul className="space-y-4">
            {FEATURES.map((f) => (
              <li key={f.text} className="flex items-center gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/[0.06] text-[#a78bfa]">
                  {f.icon}
                </span>
                <span className="text-sm text-white/70">{f.text}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Footer */}
        <p className="text-xs text-white/25">© {new Date().getFullYear()} Ragix</p>
      </div>

      {/* Right panel — form */}
      <div className="flex flex-1 flex-col items-center justify-center bg-[#f4f5f8] px-6 py-12">
        {/* Mobile-only logo */}
        <div className="mb-8 flex items-center gap-2.5 lg:hidden">
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#0d0a1f" />
            <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55" />
            <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4" />
            <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25" />
            <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa" />
            <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5" />
            <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="text-lg font-bold text-gray-900">Ragix</span>
        </div>

        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  );
}
