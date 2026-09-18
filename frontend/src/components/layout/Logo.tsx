import { LifeBuoy } from "lucide-react";

import { cn } from "@/lib/utils/cn";

/** `on="chrome"` (default) for the dark sidebar/mobile-bar surface,
 * `on="content"` for a normal light card/page background. */
export function Logo({ on = "chrome", className }: { on?: "chrome" | "content"; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <LifeBuoy className="size-4.5" aria-hidden="true" />
      </span>
      <span
        className={cn(
          "text-[15px] font-semibold tracking-tight",
          on === "chrome" ? "text-chrome-foreground" : "text-foreground"
        )}
      >
        Support Console
      </span>
    </div>
  );
}
