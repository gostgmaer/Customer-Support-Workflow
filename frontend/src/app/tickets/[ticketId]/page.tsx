"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Alert } from "@/components/ui/Alert";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { TicketDetail } from "@/features/tickets/components/TicketDetail";
import { useTicket } from "@/features/tickets/hooks";
import { getErrorMessage } from "@/lib/api/get-error-message";

function TicketDetailContent({ ticketId }: { ticketId: string }) {
  const ticket = useTicket(ticketId);

  return (
    <div className="space-y-4">
      <Link
        href="/tickets"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        Back to queue
      </Link>

      {ticket.isLoading && <FullPageSpinner />}
      {ticket.isError && <Alert variant="error">{getErrorMessage(ticket.error)}</Alert>}
      {ticket.data && <TicketDetail ticket={ticket.data} />}
    </div>
  );
}

export default function TicketDetailPage({ params }: { params: Promise<{ ticketId: string }> }) {
  const { ticketId } = use(params);
  return (
    <AuthGuard scope="staff">
      <AppShell>
        <TicketDetailContent ticketId={ticketId} />
      </AppShell>
    </AuthGuard>
  );
}
