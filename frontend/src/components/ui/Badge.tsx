import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils/cn";

type Variant = "default" | "success" | "warning" | "danger" | "accent";

const variantClasses: Record<Variant, string> = {
  default: "bg-muted text-muted-foreground",
  success: "bg-success-bg text-success",
  warning: "bg-warning-bg text-warning",
  danger: "bg-danger-bg text-danger",
  accent: "bg-accent text-accent-foreground",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: Variant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variantClasses[variant],
        className
      )}
      {...props}
    />
  );
}

const PRIORITY_VARIANT: Record<string, Variant> = {
  CRITICAL: "danger",
  HIGH: "warning",
  MEDIUM: "accent",
  LOW: "default",
};

export function PriorityBadge({ priority }: { priority: string }) {
  return <Badge variant={PRIORITY_VARIANT[priority] ?? "default"}>{priority}</Badge>;
}

const STATUS_VARIANT: Record<string, Variant> = {
  open: "warning",
  resolved: "success",
  rejected: "danger",
  awaiting_approval: "warning",
  escalated: "warning",
  active: "success",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_VARIANT[status] ?? "default"}>{status.replace(/_/g, " ")}</Badge>;
}

/**
 * Phase 15 - SLA breach is never stored server-side (no scheduler exists in
 * this codebase), so it's computed here, on-demand, from resolution_due_at
 * vs. now() - mirroring the same on-read philosophy the backend uses.
 */
export function SlaBadge({
  resolutionDueAt,
  resolvedAt,
}: {
  resolutionDueAt: string | null;
  resolvedAt: string | null;
}) {
  if (!resolutionDueAt) return null;
  const due = new Date(resolutionDueAt);
  const now = resolvedAt ? new Date(resolvedAt) : new Date();
  const diffMs = due.getTime() - now.getTime();
  const breached = diffMs < 0;

  if (resolvedAt) {
    return breached ? (
      <Badge variant="danger">SLA breached</Badge>
    ) : (
      <Badge variant="success">SLA met</Badge>
    );
  }
  if (breached) {
    return <Badge variant="danger">SLA overdue</Badge>;
  }
  const hoursLeft = Math.round(diffMs / (1000 * 60 * 60));
  const label = hoursLeft < 1 ? "<1h left" : `${hoursLeft}h left`;
  return <Badge variant={hoursLeft <= 4 ? "warning" : "default"}>{label}</Badge>;
}
