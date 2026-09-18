import { AlertCircle, CheckCircle2, Inbox, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils/cn";
import type { SupportTicket } from "@/types/api";

interface Stat {
  label: string;
  value: number;
  icon: LucideIcon;
  tone: "warning" | "success" | "danger" | "default";
}

const TONE_CLASSES: Record<Stat["tone"], string> = {
  warning: "bg-warning-bg text-warning",
  success: "bg-success-bg text-success",
  danger: "bg-danger-bg text-danger",
  default: "bg-accent text-accent-foreground",
};

function statsFrom(tickets: SupportTicket[]): Stat[] {
  const open = tickets.filter((t) => t.status === "open").length;
  const resolved = tickets.filter((t) => t.status === "resolved").length;
  const rejected = tickets.filter((t) => t.status === "rejected").length;

  return [
    { label: "Open", value: open, icon: Inbox, tone: "warning" },
    { label: "Resolved", value: resolved, icon: CheckCircle2, tone: "success" },
    { label: "Rejected", value: rejected, icon: XCircle, tone: "danger" },
    { label: "Total", value: tickets.length, icon: AlertCircle, tone: "default" },
  ];
}

export function TicketStatsRow({
  tickets,
  isLoading,
}: {
  tickets: SupportTicket[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !tickets) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[74px] w-full" />
        ))}
      </div>
    );
  }

  const stats = statsFrom(tickets);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3.5 shadow-sm"
        >
          <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-md", TONE_CLASSES[stat.tone])}>
            <stat.icon className="size-4.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="text-2xl font-semibold leading-tight tabular-nums text-foreground">{stat.value}</p>
            <p className="truncate text-xs text-muted-foreground">{stat.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
