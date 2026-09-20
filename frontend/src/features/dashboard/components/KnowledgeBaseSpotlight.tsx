import { BookOpen, ThumbsUp } from "lucide-react";
import Link from "next/link";

import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useKnowledgeArticles } from "@/features/knowledge/hooks";

export function KnowledgeBaseSpotlight() {
  const { data: articles, isLoading, isError, error } = useKnowledgeArticles({ sort: "popular", limit: 4 });

  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-foreground">Popular knowledge base articles</h2>
        <Link href="/knowledge-base" className="text-xs font-medium text-primary hover:underline">
          Browse all
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : isError ? (
        <ApiErrorState error={error} />
      ) : !articles || articles.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No articles yet"
          description="Connect a docs source or ingest a knowledge directory to populate this."
        />
      ) : (
        <ul className="divide-y divide-border">
          {articles.map((article) => (
            <li key={article.id}>
              <Link
                href={`/knowledge-base/${article.id}`}
                className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="line-clamp-1 text-sm font-medium text-foreground hover:text-primary hover:underline">
                    {article.title}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{article.category}</p>
                </div>
                {article.helpful_percent !== null && (
                  <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                    <ThumbsUp className="size-3" aria-hidden="true" />
                    {article.helpful_percent}%
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
