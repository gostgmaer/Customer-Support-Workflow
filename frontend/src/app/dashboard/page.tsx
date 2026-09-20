"use client";

import Link from "next/link";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { CommandBar } from "@/features/dashboard/components/CommandBar";
import { KnowledgeBaseSpotlight } from "@/features/dashboard/components/KnowledgeBaseSpotlight";
import { PriorityDistribution } from "@/features/dashboard/components/PriorityDistribution";
import { PriorityQueueList } from "@/features/dashboard/components/PriorityQueueList";
import { useSession } from "@/features/auth/hooks";
import { useTickets } from "@/features/tickets/hooks";

function DashboardContent() {
  const session = useSession();
  const tickets = useTickets(undefined);
  const firstName = session?.scope === "staff" ? session.id : "";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Welcome back{firstName ? `, ${firstName}` : ""}</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">Here&apos;s what&apos;s happening across the support desk.</p>
      </div>

      {tickets.isError && <ApiErrorState error={tickets.error} />}

      <CommandBar tickets={tickets.data} isLoading={tickets.isLoading} />

      <PriorityDistribution tickets={tickets.data} isLoading={tickets.isLoading} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-foreground">Needs attention</h2>
            <Link
              href="/tickets"
              className="inline-flex h-8 items-center justify-center rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              View full queue
            </Link>
          </div>
          <PriorityQueueList tickets={tickets.data} isLoading={tickets.isLoading} />
        </div>

        <KnowledgeBaseSpotlight />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGuard scope="staff">
      <AppShell>
        <DashboardContent />
      </AppShell>
    </AuthGuard>
  );
}
