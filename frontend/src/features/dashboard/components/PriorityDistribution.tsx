import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils/cn";
import type { SupportTicket } from "@/types/api";

const TIERS: { priority: string; label: string; accent: string }[] = [
  { priority: "CRITICAL", label: "Critical", accent: "border-l-danger text-danger" },
  { priority: "HIGH", label: "High", accent: "border-l-warning text-warning" },
  { priority: "MEDIUM", label: "Medium", accent: "border-l-accent-foreground text-accent-foreground" },
  { priority: "LOW", label: "Low", accent: "border-l-muted-foreground text-muted-foreground" },
];

export function PriorityDistribution({
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
          <Skeleton key={i} className="h-[76px] w-full" />
        ))}
      </div>
    );
  }

  const openTickets = tickets.filter((t) => t.status === "open");

  return (
    <div>
      <h2 className="mb-3 text-sm font-medium text-foreground">Open tickets by priority</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {TIERS.map((tier) => {
          const count = openTickets.filter((t) => t.priority === tier.priority).length;
          return (
            <div
              key={tier.priority}
              className={cn(
                "rounded-lg border-l-4 border-border bg-card px-4 py-3.5 shadow-sm",
                tier.accent.split(" ")[0]
              )}
            >
              <p className={cn("text-2xl font-semibold tabular-nums", tier.accent.split(" ")[1])}>{count}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{tier.label}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
