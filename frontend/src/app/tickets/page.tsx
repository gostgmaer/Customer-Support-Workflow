"use client";

import { useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Alert } from "@/components/ui/Alert";
import { StatusFilterTabs } from "@/features/tickets/components/StatusFilterTabs";
import { TicketQueueTable } from "@/features/tickets/components/TicketQueueTable";
import { TicketStatsRow } from "@/features/tickets/components/TicketStatsRow";
import { useTickets } from "@/features/tickets/hooks";
import { getErrorMessage } from "@/lib/api/get-error-message";

function TicketQueueContent() {
  const [status, setStatus] = useState<string | undefined>("open");
  const allTickets = useTickets(undefined);
  const filteredTickets = useTickets(status);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Ticket queue</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Tickets scoped to your role - see docs/SECURITY.md for the queue split.
        </p>
      </div>

      <TicketStatsRow tickets={allTickets.data} isLoading={allTickets.isLoading} />

      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-foreground">Queue</h2>
        <StatusFilterTabs value={status} onChange={setStatus} />
      </div>

      {filteredTickets.isError && <Alert variant="error">{getErrorMessage(filteredTickets.error)}</Alert>}

      <TicketQueueTable tickets={filteredTickets.data} isLoading={filteredTickets.isLoading} />
    </div>
  );
}

export default function TicketsPage() {
  return (
    <AuthGuard scope="staff">
      <AppShell>
        <TicketQueueContent />
      </AppShell>
    </AuthGuard>
  );
}
