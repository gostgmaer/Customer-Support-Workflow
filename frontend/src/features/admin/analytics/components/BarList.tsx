import { BarChart3 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * A dependency-free proportional bar list - this app has no charting
 * library today (checked frontend/package.json before building this) and
 * its real data volume (see docs/ARCHITECTURE.md's RAG-phase scale
 * justification) doesn't warrant adding one for a handful of category
 * counts.
 */
export function BarList({
  title,
  items,
}: {
  title: string;
  items: { label: string; count: number }[];
}) {
  const max = Math.max(1, ...items.map((item) => item.count));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {items.length === 0 ? (
          <EmptyState icon={BarChart3} title="No data yet" description="Nothing in this window." />
        ) : (
          items.map((item) => (
            <div key={item.label} className="flex items-center gap-3 text-sm">
              <span className="w-32 shrink-0 truncate text-muted-foreground">{item.label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(item.count / max) * 100}%` }}
                />
              </div>
              <span className="w-8 shrink-0 text-right font-medium text-foreground">{item.count}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
