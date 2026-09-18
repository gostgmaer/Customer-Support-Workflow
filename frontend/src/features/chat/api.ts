import { apiFetch } from "@/lib/api/client";
import type { Conversation, Message, SupportMessageResponse } from "@/types/api";

export function createConversation(channel = "web") {
  return apiFetch<Conversation>("/api/v1/support/conversations", {
    method: "POST",
    body: { channel },
  });
}

export function getConversation(conversationId: string) {
  return apiFetch<Conversation>(`/api/v1/support/conversations/${conversationId}`);
}

export function listMessages(conversationId: string) {
  return apiFetch<Message[]>(`/api/v1/support/conversations/${conversationId}/messages`);
}

export function postMessage(input: {
  conversationId: string;
  messageId: string;
  message: string;
  channel?: string;
}) {
  return apiFetch<SupportMessageResponse>("/api/v1/support/messages", {
    method: "POST",
    body: {
      conversation_id: input.conversationId,
      message_id: input.messageId,
      message: input.message,
      channel: input.channel ?? "web",
    },
  });
}
