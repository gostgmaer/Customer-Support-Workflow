"use client";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Alert } from "@/components/ui/Alert";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { useSession } from "@/features/auth/hooks";
import { ChatThread } from "@/features/chat/components/ChatThread";
import { useConversationBootstrap } from "@/features/chat/hooks";
import { getErrorMessage } from "@/lib/api/get-error-message";

function ChatPageContent() {
  const session = useSession();
  const customerId = session?.scope === "customer" ? session.id : null;
  const { conversationId, isLoading, error, startNewConversation } = useConversationBootstrap(customerId);

  if (error) {
    return (
      <div className="mx-auto max-w-md py-16">
        <Alert variant="error" title="Couldn't start a conversation">
          {getErrorMessage(error)}
        </Alert>
      </div>
    );
  }

  if (isLoading || !conversationId) return <FullPageSpinner label="Starting your conversation…" />;

  return <ChatThread conversationId={conversationId} onNewConversation={startNewConversation} />;
}

export default function ChatPage() {
  return (
    <AuthGuard scope="customer">
      <AppShell>
        <ChatPageContent />
      </AppShell>
    </AuthGuard>
  );
}
