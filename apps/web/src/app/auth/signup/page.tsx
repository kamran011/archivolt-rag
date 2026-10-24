"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

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
      <main id="main-content" className="min-h-screen flex items-center justify-center bg-bg">
        <div className="w-full max-w-md text-center">
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary-tint">
              <svg className="h-7 w-7 text-primary" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 7l9 6 9-6" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Check your email</h2>
            <p className="text-gray-500 text-sm">
              We&apos;ve sent a confirmation link to <strong>{email}</strong>. Click it to
              activate your account.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main id="main-content" className="min-h-screen flex items-center justify-center bg-bg">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-3">
            <svg width="36" height="36" viewBox="0 0 32 32" fill="none" aria-hidden>
              <rect width="32" height="32" rx="7" fill="#0d0a1f"/>
              <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55"/>
              <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4"/>
              <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25"/>
              <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa"/>
              <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5"/>
              <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <h1 className="text-3xl font-bold text-gray-900">Ragix</h1>
          </div>
          <p className="text-gray-500">Create your workspace</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 space-y-5"
        >
          {error && (
            <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Min. 8 characters"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full cursor-pointer rounded-lg bg-blue-600 text-white py-2.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Creating account…" : "Create account"}
          </button>

          <p className="text-center text-sm text-gray-500">
            Already have an account?{" "}
            <Link href="/auth/login" className="text-blue-600 hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
