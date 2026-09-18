import { Eye, ThumbsUp } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import type { KnowledgeArticleSummary } from "@/types/api";

export function ArticleCard({ article }: { article: KnowledgeArticleSummary }) {
  return (
    <Link
      href={`/knowledge-base/${article.id}`}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <Badge variant="accent" className="w-fit">
        {article.category}
      </Badge>
      <p className="line-clamp-1 font-medium text-foreground">{article.title}</p>
      <p className="line-clamp-2 text-sm text-muted-foreground">{article.summary}</p>
      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Eye className="size-3.5" aria-hidden="true" />
          {article.view_count.toLocaleString()}
        </span>
        {article.helpful_percent !== null && (
          <span className="flex items-center gap-1">
            <ThumbsUp className="size-3.5" aria-hidden="true" />
            {article.helpful_percent}%
          </span>
        )}
      </div>
    </Link>
  );
}
