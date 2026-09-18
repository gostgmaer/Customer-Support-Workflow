import { Clock, ShieldAlert } from "lucide-react";

import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import type { Conversation } from "@/types/api";

export function ConversationStatusBar({ conversation }: { conversation: Conversation }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card px-4 py-2.5 text-sm">
      <StatusBadge status={conversation.status} />
      {conversation.intent && (
        <span className="text-muted-foreground">
          {conversation.intent.replace(/_/g, " ").toLowerCase()}
        </span>
      )}
      {conversation.priority && <PriorityBadge priority={conversation.priority} />}

      {conversation.status === "awaiting_approval" && (
        <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-warning">
          <Clock className="size-3.5" aria-hidden="true" />
          Waiting on human approval - this updates automatically.
        </span>
      )}
      {conversation.status === "escalated" && (
        <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldAlert className="size-3.5" aria-hidden="true" />
          Escalated to our support team.
        </span>
      )}
    </div>
  );
}
