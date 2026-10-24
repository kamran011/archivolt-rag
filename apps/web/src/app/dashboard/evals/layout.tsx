import type { Metadata } from "next";

export const metadata: Metadata = { title: "Evaluation lab" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
