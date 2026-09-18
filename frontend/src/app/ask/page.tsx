"use client";

import Link from "next/link";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { AskKnowledgeBaseChat } from "@/features/knowledge/components/AskKnowledgeBaseChat";

function AskPageContent() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Ask a question</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Get instant answers from our knowledge base. Need something more specific? Use{" "}
          <Link href="/chat" className="text-primary underline">
            live chat
          </Link>{" "}
          instead.
        </p>
      </div>
      <AskKnowledgeBaseChat />
    </div>
  );
}

export default function AskPage() {
  return (
    <AuthGuard scope="customer">
      <AppShell>
        <AskPageContent />
      </AppShell>
    </AuthGuard>
  );
}
