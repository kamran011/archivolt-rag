"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import AuthShell from "@/components/auth/AuthShell";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });

    if (error) {
      setError(error.message);
      setLoading(false);
    } else if (data.session) {
      // Email confirmation is disabled (e.g. local dev): the user is already signed in.
      router.replace("/dashboard");
      router.refresh();
    } else {
      setSuccess(true);
      setLoading(false);
    }
  }

  if (success) {
    return (
      <AuthShell>
        <main id="main-content" className="text-center">
          <div
            className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: "rgba(106,53,255,0.15)" }}
          >
            <svg className="h-7 w-7" style={{ color: "#a78bfa" }} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7l9 6 9-6" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">Check your email</h2>
          <p className="text-sm" style={{ color: "rgba(255,255,255,0.5)" }}>
            We&apos;ve sent a confirmation link to <strong className="text-white">{email}</strong>. Click it to
            activate your account.
          </p>
        </main>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <main id="main-content" className="animate-fade-slide-up">
        <div className="mb-7">
          <h1 className="text-2xl font-bold text-white">Create your account</h1>
          <p className="mt-1 text-sm" style={{ color: "rgba(255,255,255,0.45)" }}>Get started with Ragix for free</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div
              role="alert"
              className="animate-shake rounded-lg px-4 py-3 text-sm"
              style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", color: "#fca5a5" }}
            >
              {error}
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1.5" style={{ color: "rgba(255,255,255,0.6)" }}>
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
              onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(106,53,255,0.6)")}
              onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-1.5" style={{ color: "rgba(255,255,255,0.6)" }}>
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)" }}
              onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(106,53,255,0.6)")}
              onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
              placeholder="Min. 8 characters"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full cursor-pointer rounded-lg py-2.5 text-sm font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            style={{ background: "#6a35ff", boxShadow: "0 8px 24px rgba(106,53,255,0.35)" }}
          >
            {loading ? "Creating account…" : "Create account"}
          </button>

          <p className="text-center text-sm" style={{ color: "rgba(255,255,255,0.4)" }}>
            Already have an account?{" "}
            <Link href="/auth/login" className="font-medium hover:underline" style={{ color: "#a78bfa" }}>
              Sign in
            </Link>
          </p>
        </form>
      </main>
    </AuthShell>
  );
}
