"use client";

import { MessageSquare, RotateCcw } from "lucide-react";
import { useEffect, useRef } from "react";

import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Spinner } from "@/components/ui/Spinner";

import { useConversation, useConversationSocket, useMessages, useSendMessage } from "../hooks";
import { ConversationStatusBar } from "./ConversationStatusBar";
import { MessageBubble } from "./MessageBubble";
import { MessageComposer } from "./MessageComposer";

export function ChatThread({
  conversationId,
  onNewConversation,
}: {
  conversationId: string;
  onNewConversation: () => void;
}) {
  const conversation = useConversation(conversationId);
  const messages = useMessages(conversationId);
  const sendMessage = useSendMessage(conversationId);
  useConversationSocket(conversationId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, sendMessage.isPending]);

  const isAwaitingApproval = conversation.data?.status === "awaiting_approval";

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h1 className="text-sm font-semibold">Conversation</h1>
        <Button variant="ghost" size="sm" onClick={onNewConversation}>
          <RotateCcw className="size-3.5" aria-hidden="true" />
          New conversation
        </Button>
      </div>

      {conversation.data && <ConversationStatusBar conversation={conversation.data} />}

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-12 w-2/3" />
            <Skeleton className="ml-auto h-12 w-1/2" />
            <Skeleton className="h-12 w-3/5" />
          </div>
        )}

        {messages.isError && <ApiErrorState error={messages.error} />}

        {messages.isSuccess && messages.data.length === 0 && (
          <EmptyState
            icon={MessageSquare}
            title="Say hello to get started"
            description="Ask about an order, a refund, your subscription, or anything else."
          />
        )}

        {messages.data?.map((message, index) => (
          <MessageBubble key={`${message.created_at}-${index}`} message={message} />
        ))}

        {sendMessage.isPending && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm bg-secondary px-4 py-2.5">
              <Spinner label="Assistant is responding" />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <MessageComposer
        onSend={(message) => sendMessage.mutate(message)}
        disabled={sendMessage.isPending || isAwaitingApproval}
      />
      {isAwaitingApproval && (
        <p className="border-t border-border px-4 py-2 text-center text-xs text-muted-foreground">
          A team member needs to approve this request before the conversation can continue.
        </p>
      )}
    </div>
  );
}
