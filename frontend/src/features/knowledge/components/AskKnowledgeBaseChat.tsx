"use client";

import { BookOpen, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { MessageComposer } from "@/features/chat/components/MessageComposer";
import { useAskKnowledgeBase } from "@/features/knowledge/hooks";
import { cn } from "@/lib/utils/cn";
import type { KnowledgeAskSource } from "@/types/api";

interface AskMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: KnowledgeAskSource[];
  grounded?: boolean;
}

/**
 * Stateless RAG Q&A chat shared by the customer portal and the staff
 * console (spec: "one chat window that searches RAG, open to everyone") -
 * every message round-trips through POST /api/v1/knowledge/ask, which
 * accepts either a customer or staff token. Deliberately not the same
 * component as the customer support ChatThread: this creates no
 * conversation/ticket and never calls a tool - it only ever answers from
 * whatever is in the knowledge base, or says so honestly when nothing
 * matches.
 */
export function AskKnowledgeBaseChat({ articleLinkBase }: { articleLinkBase?: string }) {
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const ask = useAskKnowledgeBase();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, ask.isPending]);

  const onSend = async (question: string) => {
    const userMessage: AskMessage = { id: crypto.randomUUID(), role: "user", content: question };
    setMessages((prev) => [...prev, userMessage]);

    try {
      const result = await ask.mutateAsync(question);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.answer,
          sources: result.sources,
          grounded: result.grounded,
        },
      ]);
    } catch {
      // useAskKnowledgeBase already toasts the error - nothing more to do
      // here, the failed question just stays visible with no reply.
    }
  };

  return (
    <div className="flex h-[calc(100vh-11rem)] min-h-[420px] flex-col rounded-lg border border-border bg-card shadow-sm">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
            <Sparkles className="size-8" aria-hidden="true" />
            <p className="font-medium text-foreground">Ask anything about our knowledge base</p>
            <p className="max-w-sm text-sm">
              e.g. &quot;What&apos;s your return policy?&quot; or &quot;How long does shipping take?&quot;
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <AskMessageBubble key={message.id} message={message} articleLinkBase={articleLinkBase} />
            ))}
            {ask.isPending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-secondary px-4 py-2.5">
                  <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
                  <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
                  <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
                </div>
              </div>
            )}
            <div ref={scrollRef} />
          </div>
        )}
      </div>
      <MessageComposer onSend={onSend} disabled={ask.isPending} />
    </div>
  );
}

function AskMessageBubble({
  message,
  articleLinkBase,
}: {
  message: AskMessage;
  articleLinkBase?: string;
}) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm break-words",
          isUser
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm bg-secondary text-secondary-foreground"
        )}
      >
        <div className="[&>*:last-child]:mb-0">
          <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
        </div>

        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-current/10 pt-2">
            {message.sources.map((source) =>
              articleLinkBase ? (
                <Link
                  key={source.id}
                  href={`${articleLinkBase}/${source.id}`}
                  className="flex items-center gap-1 rounded-full bg-background/60 px-2 py-0.5 text-xs font-medium text-foreground hover:underline"
                >
                  <BookOpen className="size-3" aria-hidden="true" />
                  {source.title}
                </Link>
              ) : (
                <span
                  key={source.id}
                  className="flex items-center gap-1 rounded-full bg-background/60 px-2 py-0.5 text-xs font-medium text-foreground"
                >
                  <BookOpen className="size-3" aria-hidden="true" />
                  {source.title}
                </span>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
