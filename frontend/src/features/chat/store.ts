import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * There is no "list my conversations" backend endpoint (see docs/API.md) -
 * this app is single-active-conversation-per-customer by design, matching
 * how the backend's own example flows work (one conversation_id per
 * session). The active conversation id is remembered per customer so a
 * page refresh continues the same thread instead of starting a new one.
 */
interface ChatState {
  activeConversationByCustomer: Record<string, string>;
  setActiveConversation: (customerId: string, conversationId: string) => void;
  clearActiveConversation: (customerId: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      activeConversationByCustomer: {},
      setActiveConversation: (customerId, conversationId) =>
        set((state) => ({
          activeConversationByCustomer: { ...state.activeConversationByCustomer, [customerId]: conversationId },
        })),
      clearActiveConversation: (customerId) =>
        set((state) => {
          const next = { ...state.activeConversationByCustomer };
          delete next[customerId];
          return { activeConversationByCustomer: next };
        }),
    }),
    { name: "csw-chat" }
  )
);
