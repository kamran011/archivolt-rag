import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to your Ragix AI knowledge workspace.",
  robots: { index: false, follow: false },
  alternates: { canonical: "https://archivolt-rag.vercel.app/auth/login" },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
