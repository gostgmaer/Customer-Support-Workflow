import { cn } from "@/lib/utils/cn";

const FILTERS: { value: string | undefined; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "rejected", label: "Rejected" },
  { value: undefined, label: "All" },
];

export function StatusFilterTabs({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  return (
    <div role="tablist" aria-label="Filter tickets by status" className="inline-flex rounded-md border border-border p-0.5">
      {FILTERS.map((filter) => (
        <button
          key={filter.label}
          role="tab"
          type="button"
          aria-selected={value === filter.value}
          onClick={() => onChange(filter.value)}
          className={cn(
            "rounded px-3 py-1.5 text-sm font-medium transition-colors",
            value === filter.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}
