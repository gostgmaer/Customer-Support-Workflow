import { format } from "date-fns";
import Link from "next/link";

import type { KnowledgeArticleSummary } from "@/types/api";

export function ArticleListRow({ article }: { article: KnowledgeArticleSummary }) {
  return (
    <Link
      href={`/knowledge-base/${article.id}`}
      className="flex items-center justify-between gap-4 px-4 py-3 transition-colors hover:bg-secondary/40"
    >
      <div className="min-w-0">
        <p className="line-clamp-1 font-medium text-foreground">{article.title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{article.category}</p>
      </div>
      <span className="shrink-0 text-xs text-muted-foreground">{format(new Date(article.updated_at), "MMM d")}</span>
    </Link>
  );
}
