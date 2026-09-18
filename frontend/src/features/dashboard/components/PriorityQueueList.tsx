import { formatDistanceToNow } from "date-fns";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { PriorityBadge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import type { SupportTicket } from "@/types/api";

const PRIORITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

export function PriorityQueueList({ tickets, isLoading }: { tickets: SupportTicket[] | undefined; isLoading: boolean }) {
  if (isLoading || !tickets) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  const queue = tickets
    .filter((t) => t.status === "open")
    .sort((a, b) => (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9))
    .slice(0, 6);

  if (queue.length === 0) {
    return (
      <EmptyState icon={CheckCircle2} title="Queue is clear" description="No open tickets need attention right now." />
    );
  }

  return (
    <div className="divide-y divide-border rounded-lg border border-border bg-card shadow-sm">
      {queue.map((ticket) => (
        <Link
          key={ticket.id}
          href={`/tickets/${ticket.id}`}
          className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-secondary/40"
        >
          <div className="min-w-0 flex-1">
            <p className="line-clamp-1 text-sm font-medium text-foreground">
              {ticket.summary || ticket.customer_problem}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">{ticket.intent.replace(/_/g, " ")}</p>
          </div>
          <PriorityBadge priority={ticket.priority} />
          <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
            {formatDistanceToNow(new Date(ticket.created_at), { addSuffix: true })}
          </span>
        </Link>
      ))}
    </div>
  );
}
