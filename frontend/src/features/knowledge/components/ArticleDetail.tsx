"use client";

import { format } from "date-fns";
import { Calendar, Download, Eye, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import Link from "next/link";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  useDownloadKnowledgeArticleFile,
  useKnowledgeArticle,
  useRelatedKnowledgeArticles,
  useSubmitKnowledgeFeedback,
} from "@/features/knowledge/hooks";

/** Article bodies now come from four different sources (plain .md/.txt
 * seed files, and .pdf/.docx uploads extracted via app.rag.file_extractors)
 * - a .docx's headings/tables arrive as real markdown, so this renders
 * `raw_text` as markdown rather than preformatted plain text, with GFM
 * table support for the pipe-table syntax file_extractors emits. */
const ARTICLE_MARKDOWN_COMPONENTS: Components = {
  h1: ({ children }) => <h2 className="mb-2 mt-5 text-lg font-semibold first:mt-0">{children}</h2>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1.5 mt-3 font-semibold first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="mb-3 leading-relaxed last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-primary underline decoration-primary/40">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-secondary/60">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-border px-3 py-1.5 text-left font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="border border-border px-3 py-1.5">{children}</td>,
};

export function ArticleDetail({ articleId }: { articleId: string }) {
  const article = useKnowledgeArticle(articleId);
  const related = useRelatedKnowledgeArticles(articleId);
  const feedback = useSubmitKnowledgeFeedback(articleId);
  const downloadFile = useDownloadKnowledgeArticleFile();

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

        <div className="rounded-lg border border-border bg-card p-5 text-sm text-foreground shadow-sm">
          <Markdown remarkPlugins={[remarkGfm]} components={ARTICLE_MARKDOWN_COMPONENTS}>
            {doc.raw_text}
          </Markdown>
        </div>

        <div className="rounded-lg border border-border bg-card p-5 text-center shadow-sm">
          <p className="mb-3 text-sm font-medium text-foreground">Was this article helpful?</p>
          <div className="flex justify-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => feedback.mutate(true)}
              disabled={feedback.isPending}
              className="hover:bg-success-bg hover:text-success"
            >
              <ThumbsUp className="size-4" aria-hidden="true" />
              Yes
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => feedback.mutate(false)}
              disabled={feedback.isPending}
              className="hover:bg-danger-bg hover:text-danger"
            >
              <ThumbsDown className="size-4" aria-hidden="true" />
              No
            </Button>
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
          {doc.created_by && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <UserRound className="size-3.5 shrink-0" aria-hidden="true" />
              <span>Uploaded by {doc.created_by}</span>
            </div>
          )}
          <div className="border-t border-border pt-3 text-xs text-muted-foreground">
            Source: {doc.source} · v{doc.version}
          </div>
        </dl>

        {doc.has_original_file && (
          <Button
            type="button"
            variant="outline"
            onClick={() => downloadFile.mutate(doc.id)}
            isLoading={downloadFile.isPending}
            className="mt-4 w-full"
          >
            <Download className="size-4" aria-hidden="true" />
            Download original file
          </Button>
        )}
      </aside>
    </div>
  );
}
