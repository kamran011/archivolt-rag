import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ragix — AI Knowledge Platform",
  description:
    "Upload your documents, ask questions, get answers with cited sources. Ragix is a production-grade RAG platform for teams who need reliable AI answers.",
  alternates: { canonical: "https://archivolt-rag.vercel.app" },
};

export default async function Home() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) redirect("/dashboard");

  return (
    <main id="main-content" className="min-h-screen bg-bg">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-2.5">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#0d0a1f" />
            <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55" />
            <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4" />
            <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25" />
            <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa" />
            <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5" />
            <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="text-lg font-bold text-gray-900 tracking-tight">Ragix</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/auth/login"
            className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/auth/signup"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Get started free
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-6 pt-20 pb-16 text-center">
        <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-4 py-1.5 text-xs font-medium text-primary mb-6">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          Production-grade RAG platform
        </div>
        <h1 className="text-5xl font-bold text-gray-900 leading-tight tracking-tight mb-6">
          AI answers your team<br />can actually trust
        </h1>
        <p className="text-lg text-gray-500 max-w-2xl mx-auto mb-10 leading-relaxed">
          Upload your documents, ask questions in plain English, and get cited answers backed by evidence.
          Ragix retrieves the right context, verifies claims, and cites every source.
        </p>
        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link
            href="/auth/signup"
            className="rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white hover:bg-blue-700 transition-colors shadow-lg shadow-primary/20"
          >
            Start for free
          </Link>
          <Link
            href="/auth/login"
            className="rounded-xl border border-gray-200 bg-white px-6 py-3 text-sm font-semibold text-gray-700 hover:border-gray-300 hover:bg-gray-50 transition-colors"
          >
            Sign in to workspace
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          {[
            {
              icon: (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                  <circle cx="11" cy="11" r="8" /><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35" />
                </svg>
              ),
              title: "Retrieval that works",
              body: "Hybrid search with semantic + keyword ranking and smart re-ranking so the most relevant chunks always surface.",
            },
            {
              icon: (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              ),
              title: "Verified answers",
              body: "Every claim is checked against the source. Conflicting evidence is flagged. Uncertain answers are flagged as uncertain.",
            },
            {
              icon: (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              ),
              title: "Full observability",
              body: "See exactly what chunks were retrieved, how they were ranked, and why an answer was generated — or not.",
            },
          ].map((f) => (
            <div key={f.title} className="rounded-2xl border border-border bg-white p-6">
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                {f.icon}
              </div>
              <h2 className="font-semibold text-gray-900 mb-2">{f.title}</h2>
              <p className="text-sm text-gray-500 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-8 text-center text-xs text-gray-400">
        © {new Date().getFullYear()} Ragix. All rights reserved.
      </footer>
    </main>
  );
}
