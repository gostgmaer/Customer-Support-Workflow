import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils/cn";

type Variant = "error" | "success" | "info";

const config: Record<Variant, { icon: typeof Info; classes: string }> = {
  error: { icon: AlertTriangle, classes: "bg-danger-bg text-danger border-danger/20" },
  success: { icon: CheckCircle2, classes: "bg-success-bg text-success border-success/20" },
  info: { icon: Info, classes: "bg-accent text-accent-foreground border-transparent" },
};

export function Alert({
  variant = "info",
  title,
  children,
}: {
  variant?: Variant;
  title?: string;
  children: ReactNode;
}) {
  const { icon: Icon, classes } = config[variant];
  return (
    <div role="alert" className={cn("flex gap-3 rounded-md border px-4 py-3 text-sm", classes)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div>
        {title && <p className="font-medium">{title}</p>}
        <div className={title ? "mt-0.5 opacity-90" : ""}>{children}</div>
      </div>
    </div>
  );
}
