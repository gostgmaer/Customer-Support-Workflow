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
