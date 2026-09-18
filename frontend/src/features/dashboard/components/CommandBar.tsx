import { Skeleton } from "@/components/ui/Skeleton";
import type { SupportTicket } from "@/types/api";

interface Metric {
  label: string;
  value: number;
}

function metricsFrom(tickets: SupportTicket[]): Metric[] {
  const open = tickets.filter((t) => t.status === "open").length;
  const awaiting = tickets.filter((t) => t.status === "awaiting_approval" || t.status === "escalated").length;
  const resolved = tickets.filter((t) => t.status === "resolved").length;
  const critical = tickets.filter((t) => t.priority === "CRITICAL" && t.status === "open").length;

  return [
    { label: "Open tickets", value: open },
    { label: "Awaiting approval", value: awaiting },
    { label: "Resolved", value: resolved },
    { label: "Critical open", value: critical },
  ];
}

export function CommandBar({ tickets, isLoading }: { tickets: SupportTicket[] | undefined; isLoading: boolean }) {
  if (isLoading || !tickets) {
    return <Skeleton className="h-[104px] w-full rounded-xl" />;
  }

  const metrics = metricsFrom(tickets);

  return (
    <div className="flex flex-col gap-5 rounded-xl bg-chrome px-5 py-4 text-chrome-foreground shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2.5">
        <span className="relative flex size-2.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-75" />
          <span className="relative inline-flex size-2.5 rounded-full bg-success" />
        </span>
        <div>
          <p className="text-sm font-semibold">Support desk live</p>
          <p className="text-xs text-chrome-muted">{tickets.length} tickets tracked</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-8 gap-y-3 sm:flex sm:items-center sm:gap-8">
        {metrics.map((metric) => (
          <div key={metric.label} className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-wide text-chrome-muted">{metric.label}</p>
            <p className="text-2xl font-semibold leading-tight tabular-nums">{metric.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
