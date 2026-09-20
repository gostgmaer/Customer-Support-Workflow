"use client";

import { BookOpen, MessageCircleQuestion, Plus, Search, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { useSession } from "@/features/auth/hooks";
import { ArticleCard } from "@/features/knowledge/components/ArticleCard";
import { ArticleListRow } from "@/features/knowledge/components/ArticleListRow";
import { AskKnowledgeBaseChat } from "@/features/knowledge/components/AskKnowledgeBaseChat";
import { CategoryGrid } from "@/features/knowledge/components/CategoryGrid";
import { UploadArticleDialog } from "@/features/knowledge/components/UploadArticleDialog";
import { useKnowledgeArticles, useKnowledgeCategories } from "@/features/knowledge/hooks";
import { cn } from "@/lib/utils/cn";

function KnowledgeBaseContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const category = searchParams.get("category") ?? undefined;
  const q = searchParams.get("q") ?? undefined;
  const [draft, setDraft] = useState(q ?? "");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [mode, setMode] = useState<"browse" | "ask">("browse");

  const session = useSession();
  const isAdmin = session?.scope === "staff" && session.role === "ADMIN";

  const categories = useKnowledgeCategories();
  const isFiltered = !!category || !!q;

  const results = useKnowledgeArticles({ category, q, limit: 50 });
  const popular = useKnowledgeArticles({ sort: "popular", limit: 4 });
  const recent = useKnowledgeArticles({ sort: "recent", limit: 6 });

  const applyFilters = (next: { category?: string; q?: string }) => {
    const params = new URLSearchParams();
    if (next.category) params.set("category", next.category);
    if (next.q) params.set("q", next.q);
    router.push(params.toString() ? `/knowledge-base?${params.toString()}` : "/knowledge-base");
  };

  const onSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    applyFilters({ q: draft || undefined, category });
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div className="inline-flex rounded-lg border border-border bg-card p-1 shadow-sm">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-pressed={mode === "browse"}
            onClick={() => setMode("browse")}
            className={cn(
              "rounded-md",
              mode === "browse"
                ? "bg-accent text-accent-foreground hover:bg-accent"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <BookOpen className="size-4" aria-hidden="true" />
            Browse
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-pressed={mode === "ask"}
            onClick={() => setMode("ask")}
            className={cn(
              "rounded-md",
              mode === "ask"
                ? "bg-accent text-accent-foreground hover:bg-accent"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MessageCircleQuestion className="size-4" aria-hidden="true" />
            Ask
          </Button>
        </div>

        {isAdmin && mode === "browse" && (
          <Button size="sm" onClick={() => setUploadOpen(true)}>
            <Plus className="size-4" aria-hidden="true" />
            Add article
          </Button>
        )}
      </div>

      {isAdmin && <UploadArticleDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />}

      {mode === "ask" ? (
        <AskKnowledgeBaseChat articleLinkBase="/knowledge-base" />
      ) : (
        <>
          <div className="rounded-xl border border-border bg-card px-6 py-10 text-center shadow-sm sm:px-10">
            <h1 className="text-2xl font-semibold text-foreground sm:text-3xl">How can we help you?</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Search the knowledge base or browse by category.
            </p>
            <form onSubmit={onSearchSubmit} className="relative mx-auto mt-6 max-w-lg">
              <Search
                className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Search articles..."
                className="h-11 pl-10"
              />
            </form>
          </div>

          {isFiltered ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium text-foreground">
                  {category ? `Category: ${category}` : `Search: "${q}"`}
                  {results.data && <span className="ml-2 text-muted-foreground">({results.data.length})</span>}
                </h2>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setDraft("");
                    applyFilters({});
                  }}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3.5" aria-hidden="true" />
                  Clear
                </Button>
              </div>

              {results.isError && <ApiErrorState error={results.error} />}

              {results.isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : results.data && results.data.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {results.data.map((article) => (
                    <ArticleCard key={article.id} article={article} />
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={BookOpen}
                  title="No articles found"
                  description="Try a different search or category."
                />
              )}
            </div>
          ) : (
            <>
              <div>
                <h2 className="mb-3 text-sm font-medium text-foreground">Browse by category</h2>
                <CategoryGrid
                  categories={categories.data}
                  isLoading={categories.isLoading}
                  onSelect={(c) => applyFilters({ category: c })}
                />
              </div>

              <div>
                <h2 className="mb-3 text-sm font-medium text-foreground">Popular articles</h2>
                {popular.isLoading ? (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-[140px] w-full" />
                    ))}
                  </div>
                ) : popular.data && popular.data.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {popular.data.map((article) => (
                      <ArticleCard key={article.id} article={article} />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={BookOpen}
                    title="No articles yet"
                    description="Ingest a knowledge directory or connect a docs source to populate the knowledge base."
                  />
                )}
              </div>

              {recent.data && recent.data.length > 0 && (
                <div>
                  <h2 className="mb-3 text-sm font-medium text-foreground">Recently updated</h2>
                  <div className="divide-y divide-border rounded-lg border border-border bg-card shadow-sm">
                    {recent.data.map((article) => (
                      <ArticleListRow key={article.id} article={article} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default function KnowledgeBasePage() {
  return (
    <AuthGuard scope="staff">
      <AppShell>
        <KnowledgeBaseContent />
      </AppShell>
    </AuthGuard>
  );
}
