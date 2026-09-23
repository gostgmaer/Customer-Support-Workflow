import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils/cn";

export function StatTile({
  label,
  value,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone?: "default" | "danger" | "success";
}) {
  return (
    <Card className="flex items-center gap-3 px-4 py-3.5">
      <div
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-md",
          tone === "danger" && "bg-danger-bg text-danger",
          tone === "success" && "bg-success-bg text-success",
          tone === "default" && "bg-secondary text-muted-foreground"
        )}
      >
        <Icon className="size-4.5" aria-hidden="true" />
      </div>
      <div>
        <p className="text-lg font-semibold leading-tight text-foreground">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </Card>
  );
}
