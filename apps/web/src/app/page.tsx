import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { Metadata } from "next";
import LandingPage from "@/components/landing/LandingPage";

export const metadata: Metadata = {
  title: { absolute: "Ragix — AI Knowledge Platform" },
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

  return <LandingPage />;
}
