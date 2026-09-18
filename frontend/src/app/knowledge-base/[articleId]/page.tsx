"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ArticleDetail } from "@/features/knowledge/components/ArticleDetail";

function ArticlePageContent() {
  const params = useParams<{ articleId: string }>();

  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link href="/knowledge-base" className="hover:text-foreground hover:underline">
          Knowledge base
        </Link>
        <ChevronRight className="size-3.5" aria-hidden="true" />
        <span className="text-foreground">Article</span>
      </nav>

      <ArticleDetail articleId={params.articleId} />
    </div>
  );
}

export default function KnowledgeArticlePage() {
  return (
    <AuthGuard scope="staff">
      <AppShell>
        <ArticlePageContent />
      </AppShell>
    </AuthGuard>
  );
}
