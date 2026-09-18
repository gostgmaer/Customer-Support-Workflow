"use client";

import { formatDistanceToNow } from "date-fns";
import { Bug, Inbox } from "lucide-react";
import Link from "next/link";

import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils/cn";
import type { SupportTicket } from "@/types/api";

const PRIORITY_ACCENT: Record<string, string> = {
  CRITICAL: "border-l-danger",
  HIGH: "border-l-warning",
  MEDIUM: "border-l-accent-foreground",
  LOW: "border-l-transparent",
};

export function TicketQueueTable({
  tickets,
  isLoading,
}: {
  tickets: SupportTicket[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  if (!tickets || tickets.length === 0) {
    return <EmptyState icon={Inbox} title="No tickets here" description="This queue is empty right now." />;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-secondary/60 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-2.5">
                Summary
              </th>
              <th scope="col" className="px-4 py-2.5">
                Intent
              </th>
              <th scope="col" className="px-4 py-2.5">
                Priority
              </th>
              <th scope="col" className="px-4 py-2.5">
                Status
              </th>
              <th scope="col" className="px-4 py-2.5">
                Opened
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {tickets.map((ticket) => (
              <tr
                key={ticket.id}
                className={cn(
                  "border-l-2 transition-colors hover:bg-secondary/40",
                  PRIORITY_ACCENT[ticket.priority] ?? "border-l-transparent"
                )}
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/tickets/${ticket.id}`}
                    className="line-clamp-1 font-medium text-foreground hover:text-primary hover:underline"
                  >
                    {ticket.summary || ticket.customer_problem}
                  </Link>
                  {ticket.external_ref && (
                    <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <Bug className="size-3" aria-hidden="true" />
                      {ticket.external_ref}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground">{ticket.intent.replace(/_/g, " ")}</td>
                <td className="px-4 py-3">
                  <PriorityBadge priority={ticket.priority} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={ticket.status} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                  {formatDistanceToNow(new Date(ticket.created_at), { addSuffix: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
