import type { Metadata } from "next";

export const metadata: Metadata = { title: "Create workspace" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
