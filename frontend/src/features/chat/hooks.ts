import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useChatStore } from "@/features/chat/store";
import { useAuthStore } from "@/store/auth-store";
import { toast } from "@/store/toast-store";
import type { Message, SupportMessageResponse } from "@/types/api";

import { createConversation, getConversation, listMessages, postMessage, submitFeedback } from "./api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Resolves (and, on first use, creates) the customer's active conversation.
 * Deliberately a query + mutation pair, not a manual useEffect+setState -
 * this is exactly the "fetch data, then store it" case TanStack Query
 * owns (see repository.md: "components should not manage fetch logic
 * manually").
 */
export function useConversationBootstrap(customerId: string | null) {
  const queryClient = useQueryClient();
  const activeByCustomer = useChatStore((state) => state.activeConversationByCustomer);
  const setActiveConversation = useChatStore((state) => state.setActiveConversation);

  const bootstrap = useQuery({
    queryKey: ["conversation-bootstrap", customerId],
    queryFn: async () => {
      const stored = customerId ? activeByCustomer[customerId] : undefined;
      if (stored) return stored;
      const conversation = await createConversation();
      setActiveConversation(customerId as string, conversation.id);
      return conversation.id;
    },
    enabled: !!customerId,
    staleTime: Infinity,
  });

  const startNew = useMutation({
    mutationFn: () => createConversation(),
    onSuccess: (conversation) => {
      if (!customerId) return;
      setActiveConversation(customerId, conversation.id);
      queryClient.setQueryData(["conversation-bootstrap", customerId], conversation.id);
    },
  });

  return {
    conversationId: bootstrap.data ?? null,
    isLoading: bootstrap.isLoading,
    error: bootstrap.error,
    startNewConversation: () => startNew.mutate(),
  };
}

export function useConversation(conversationId: string | null) {
  return useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => getConversation(conversationId as string),
    enabled: !!conversationId,
    // A pending refund confirmation resolves out-of-band (staff approval) -
    // poll gently so the customer sees the outcome without a manual refresh.
    refetchInterval: (query) => (query.state.data?.status === "awaiting_approval" ? 5000 : false),
  });
}

export function useMessages(conversationId: string | null) {
  return useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => listMessages(conversationId as string),
    enabled: !!conversationId,
  });
}

export function useSendMessage(conversationId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (message: string) =>
      postMessage({ conversationId, messageId: crypto.randomUUID(), message }),
    onMutate: async (message) => {
      await queryClient.cancelQueries({ queryKey: ["messages", conversationId] });
      const previous = queryClient.getQueryData<Message[]>(["messages", conversationId]);
      const optimistic: Message = { role: "customer", content: message, created_at: new Date().toISOString() };
      queryClient.setQueryData<Message[]>(["messages", conversationId], (current) => [
        ...(current ?? []),
        optimistic,
      ]);
      return { previous };
    },
    onError: (error, _message, context) => {
      queryClient.setQueryData(["messages", conversationId], context?.previous);
      toast.error("Message failed to send", error instanceof Error ? error.message : undefined);
    },
    onSuccess: (data: SupportMessageResponse) => {
      if (data.response) {
        queryClient.setQueryData<Message[]>(["messages", conversationId], (current) => [
          ...(current ?? []),
          { role: "assistant", content: data.response as string, created_at: new Date().toISOString() },
        ]);
      }
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    },
  });
}

export function useSubmitFeedback(conversationId: string) {
  return useMutation({
    mutationFn: ({ rating, comment }: { rating: number; comment?: string }) =>
      submitFeedback(conversationId, rating, comment),
    onError: (error) => {
      toast.error("Couldn't submit feedback", error instanceof Error ? error.message : undefined);
    },
  });
}

/**
 * Best-effort live push for a storefront webhook event landing on this
 * conversation while the customer is looking at it (spec: Phase 10.3).
 * On any message, invalidates the exact same two query keys
 * useSendMessage's own onSuccess already invalidates above - no new
 * cache surface, the existing REST hooks simply refetch. A browser
 * WebSocket can't set a custom Authorization header, so the JWT travels
 * as a query param (see app.api.routes.support.conversation_socket).
 */
export function useConversationSocket(
  conversationId: string | null,
  // Phase 15 - a `ticket_decision` push now carries `prompt_csat: true` when
  // the ticket reached a genuine terminal state (not the reopen-on-
  // execution-failure branch) - see app.workflow.runner.resume_workflow.
  // Optional so every existing caller keeps working unchanged.
  onPromptCsat?: () => void
) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!conversationId) return;
    const token = useAuthStore.getState().session?.token;
    if (!token) return;

    const wsBaseUrl = API_BASE_URL.replace(/^http/, "ws");
    const socket = new WebSocket(
      `${wsBaseUrl}/api/v1/support/ws/conversations/${conversationId}?token=${token}`
    );
    socket.onmessage = (event) => {
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      try {
        const payload = JSON.parse(event.data as string);
        if (payload?.prompt_csat === true) {
          onPromptCsat?.();
        }
      } catch {
        // Not JSON, or shape we don't recognize - the invalidation above
        // already handled the "something changed, refetch" case.
      }
    };

    return () => socket.close();
  }, [conversationId, queryClient, onPromptCsat]);
}
