import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/utils/cn";

// Radix Tabs requires string values - "all" stands in for the external
// API's `undefined` ("no status filter"), converted at the two edges
// below so callers never see this internal detail.
const ALL_VALUE = "all";

const FILTERS: { value: string; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "rejected", label: "Rejected" },
  { value: ALL_VALUE, label: "All" },
];

export function StatusFilterTabs({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  return (
    <TabsPrimitive.Root
      value={value ?? ALL_VALUE}
      onValueChange={(next) => onChange(next === ALL_VALUE ? undefined : next)}
    >
      <TabsPrimitive.List
        aria-label="Filter tickets by status"
        className="inline-flex rounded-md border border-border p-0.5"
      >
        {FILTERS.map((filter) => (
          <TabsPrimitive.Trigger
            key={filter.value}
            value={filter.value}
            className={cn(
              "rounded px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors",
              "hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:hover:text-primary-foreground"
            )}
          >
            {filter.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  );
}
