import { ChevronRight } from "lucide-react";

import { Skeleton } from "@/components/ui/Skeleton";
import { iconForCategory } from "@/features/knowledge/category-icons";
import type { KnowledgeCategorySummary } from "@/types/api";

export function CategoryGrid({
  categories,
  isLoading,
  onSelect,
}: {
  categories: KnowledgeCategorySummary[] | undefined;
  isLoading: boolean;
  onSelect: (category: string) => void;
}) {
  if (isLoading || !categories) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[92px] w-full" />
        ))}
      </div>
    );
  }

  if (categories.length === 0) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {categories.map((cat) => {
        const Icon = iconForCategory(cat.category);
        return (
          <button
            key={cat.category}
            type="button"
            onClick={() => onSelect(cat.category)}
            className="group flex items-start gap-3.5 rounded-lg border border-border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Icon className="size-5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-foreground">{cat.category}</p>
              <p className="mt-1 flex items-center gap-1 text-sm text-primary">
                {cat.article_count} {cat.article_count === 1 ? "article" : "articles"}
                <ChevronRight
                  className="size-3.5 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
}
