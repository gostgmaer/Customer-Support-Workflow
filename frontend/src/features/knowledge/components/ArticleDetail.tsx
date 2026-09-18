"use client";

import { format } from "date-fns";
import { Calendar, Eye, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";

import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { useKnowledgeArticle, useRelatedKnowledgeArticles, useSubmitKnowledgeFeedback } from "@/features/knowledge/hooks";

export function ArticleDetail({ articleId }: { articleId: string }) {
  const article = useKnowledgeArticle(articleId);
  const related = useRelatedKnowledgeArticles(articleId);
  const feedback = useSubmitKnowledgeFeedback(articleId);

  if (article.isError) {
    return <ApiErrorState error={article.error} />;
  }

  if (article.isLoading || !article.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const doc = article.data;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0 space-y-6">
        <div>
          <Badge variant="accent" className="mb-2">
            {doc.category}
          </Badge>
          <h1 className="text-2xl font-semibold text-foreground">{doc.title}</h1>
        </div>

        <div className="whitespace-pre-wrap rounded-lg border border-border bg-card p-5 text-sm leading-relaxed text-foreground shadow-sm">
          {doc.raw_text}
        </div>

        <div className="rounded-lg border border-border bg-card p-5 text-center shadow-sm">
          <p className="mb-3 text-sm font-medium text-foreground">Was this article helpful?</p>
          <div className="flex justify-center gap-3">
            <button
              type="button"
              onClick={() => feedback.mutate(true)}
              disabled={feedback.isPending}
              className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-success-bg hover:text-success disabled:pointer-events-none disabled:opacity-50"
            >
              <ThumbsUp className="size-4" aria-hidden="true" />
              Yes
            </button>
            <button
              type="button"
              onClick={() => feedback.mutate(false)}
              disabled={feedback.isPending}
              className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-danger-bg hover:text-danger disabled:pointer-events-none disabled:opacity-50"
            >
              <ThumbsDown className="size-4" aria-hidden="true" />
              No
            </button>
          </div>
        </div>

        {related.data && related.data.length > 0 && (
          <div>
            <h2 className="mb-3 text-sm font-medium text-foreground">Related articles</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {related.data.map((a) => (
                <Link
                  key={a.id}
                  href={`/knowledge-base/${a.id}`}
                  className="rounded-lg border border-border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
                >
                  <Badge variant="accent" className="mb-2">
                    {a.category}
                  </Badge>
                  <p className="line-clamp-1 font-medium text-foreground">{a.title}</p>
                  <p className="line-clamp-2 mt-1 text-sm text-muted-foreground">{a.summary}</p>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>

      <aside className="h-fit rounded-lg border border-border bg-card p-4 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Article info</p>
        <dl className="mt-3 space-y-3 text-sm">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Calendar className="size-3.5 shrink-0" aria-hidden="true" />
            <span>Updated {format(new Date(doc.updated_at), "MMM d, yyyy")}</span>
          </div>
          <div className="flex items-center gap-2 text-muted-foreground">
            <Eye className="size-3.5 shrink-0" aria-hidden="true" />
            <span>{doc.view_count.toLocaleString()} views</span>
          </div>
          {doc.helpful_percent !== null && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <ThumbsUp className="size-3.5 shrink-0" aria-hidden="true" />
              <span>{doc.helpful_percent}% found this helpful</span>
            </div>
          )}
          <div className="border-t border-border pt-3 text-xs text-muted-foreground">
            Source: {doc.source} · v{doc.version}
          </div>
        </dl>
      </aside>
    </div>
  );
}
