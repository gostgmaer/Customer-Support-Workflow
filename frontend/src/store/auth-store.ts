import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { StaffRole } from "@/types/api";

/**
 * The backend issues plain bearer JWTs (no cookie session - see
 * docs/SECURITY.md), so this is the only place the token lives. It is
 * persisted to localStorage so a refresh doesn't log the user out.
 *
 * Trade-off, stated explicitly: a JWT in localStorage is readable by any
 * script that runs on this origin, so an XSS bug elsewhere in the app
 * could exfiltrate it - the standard risk of a token-in-storage SPA
 * talking directly to an API on a different origin, as this backend does
 * (no server-side session to put in an httpOnly cookie instead). Mitigate
 * by never rendering unsanitized user/LLM content as HTML (see
 * MessageBubble) and keeping JWT_EXPIRY_MINUTES short server-side.
 */
export type Session =
  | {
      scope: "customer";
      token: string;
      id: string;
      name: string;
    }
  | {
      scope: "staff";
      token: string;
      id: string;
      role: StaffRole;
    };

interface AuthState {
  session: Session | null;
  hasHydrated: boolean;
  setSession: (session: Session) => void;
  logout: () => void;
  setHasHydrated: (value: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      session: null,
      hasHydrated: false,
      setSession: (session) => set({ session }),
      logout: () => set({ session: null }),
      setHasHydrated: (value) => set({ hasHydrated: value }),
    }),
    {
      name: "csw-auth",
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);
