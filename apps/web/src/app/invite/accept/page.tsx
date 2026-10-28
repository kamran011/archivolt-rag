"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import AuthShell from "@/components/auth/AuthShell";

type Stage =
  | "waiting"   // waiting for Supabase to exchange the invite token from the URL hash
  | "ready"     // user is authenticated — show "Accept invitation" button
  | "accepting" // POST in flight
  | "done"      // success, about to redirect
  | "error";

// useSearchParams needs a Suspense boundary, or the static prerender fails the build.
export default function InviteAcceptPage() {
  return (
    <Suspense>
      <InviteAccept />
    </Suspense>
  );
}

function InviteAccept() {
  const router = useRouter();
  const params = useSearchParams();
  const inviteId = params.get("invite");
  const orgId = params.get("org");

  const [stage, setStage] = useState<Stage>("waiting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Supabase puts access_token + refresh_token in the URL hash after the user
  // clicks the invite email link. onAuthStateChange picks it up and fires
  // SIGNED_IN. We wait for that before showing the accept button.
  useEffect(() => {
    const supabase = createClient();
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (session) {
          setStage("ready");
        }
      }
    );
    // Also check if already signed in (page refresh after clicking the link)
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) setStage("ready");
    });
    return () => subscription.unsubscribe();
  }, []);

  async function accept() {
    if (!inviteId) {
      setErrorMsg("Invalid invitation link — invite ID is missing.");
      setStage("error");
      return;
    }
    setStage("accepting");
    try {
      await api.post(`/api/v1/organizations/invitations/${inviteId}/accept`, {});
      setStage("done");
      setTimeout(() => router.replace("/dashboard"), 1500);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to accept invitation.");
      setStage("error");
    }
  }

  if (!inviteId || !orgId) {
    return (
      <AuthShell>
        <main id="main-content" className="text-center">
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Invalid link</h1>
          <p className="text-sm text-gray-500">This invitation link is incomplete or has expired.</p>
        </main>
      </AuthShell>
    );
  }

  if (stage === "done") {
    return (
      <AuthShell>
        <main id="main-content" className="text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
            <svg className="h-7 w-7 text-green-600" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">You&apos;re in!</h2>
          <p className="text-sm text-gray-500">Redirecting to the dashboard…</p>
        </main>
      </AuthShell>
    );
  }

  if (stage === "error") {
    return (
      <AuthShell>
        <main id="main-content" className="text-center">
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Something went wrong</h2>
          <p className="text-sm text-red-600">{errorMsg}</p>
          <a href="/auth/login" className="mt-4 inline-block text-sm text-primary hover:underline">
            Go to sign in
          </a>
        </main>
      </AuthShell>
    );
  }

  if (stage === "waiting") {
    return (
      <AuthShell>
        <main id="main-content" className="text-center">
          <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-4 border-primary/20 border-t-primary" aria-hidden />
          <p className="text-sm text-gray-500">Verifying invitation…</p>
          <p className="mt-4 text-xs text-gray-400">
            If nothing happens,{" "}
            <a href="/auth/login" className="text-primary hover:underline">
              sign in first
            </a>{" "}
            then click the invite link again.
          </p>
        </main>
      </AuthShell>
    );
  }

  // stage === "ready" or "accepting"
  return (
    <AuthShell>
      <main id="main-content" className="animate-fade-slide-up">
        <div className="mb-7">
          <h1 className="text-2xl font-bold text-gray-900">Accept invitation</h1>
          <p className="mt-1 text-sm text-gray-500">
            You&apos;ve been invited to join an organization on Ragix.
          </p>
        </div>

        <button
          onClick={() => void accept()}
          disabled={stage === "accepting"}
          className="w-full cursor-pointer rounded-lg bg-primary text-white py-2.5 text-sm font-medium hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {stage === "accepting" ? "Accepting…" : "Accept invitation"}
        </button>

        <p className="mt-4 text-center text-xs text-gray-400">
          Wrong account?{" "}
          <a href="/auth/login" className="text-primary hover:underline">
            Sign in with a different email
          </a>
        </p>
      </main>
    </AuthShell>
  );
}
