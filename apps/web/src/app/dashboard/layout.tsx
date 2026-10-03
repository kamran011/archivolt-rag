import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import DashboardChrome from "@/components/layout/DashboardChrome";
import { OrganizationProvider } from "@/providers/OrganizationProvider";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/auth/login");

  return (
    <OrganizationProvider>
      <DashboardChrome user={user}>{children}</DashboardChrome>
    </OrganizationProvider>
  );
}
