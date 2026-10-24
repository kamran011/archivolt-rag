import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create Account — Ragix",
  description: "Create your Ragix workspace and start querying your documents with AI.",
  robots: { index: false, follow: false },
  alternates: { canonical: "https://archivolt-rag.vercel.app/auth/signup" },
};

export default function SignupLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
