"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { FullPageSpinner } from "@/components/ui/Spinner";
import { isJwtExpired } from "@/lib/jwt";
import { useAuthStore } from "@/store/auth-store";
import { toast } from "@/store/toast-store";
import type { StaffRole } from "@/types/api";

/**
 * Client-side route protection. The token lives in localStorage (see
 * store/auth-store.ts), which the Next.js edge middleware can't read, so
 * this guard - not middleware.ts - is the enforcement point for "which
 * page can render." It is a UX gate, not a security boundary: the actual
 * boundary is the backend re-checking the token on every request (see
 * docs/SECURITY.md) - a user can't get data they aren't authorized for
 * just by getting past this guard.
 */
export function AuthGuard({
  scope,
  roles,
  children,
}: {
  scope: "customer" | "staff";
  roles?: StaffRole[];
  children: ReactNode;
}) {
  const session = useAuthStore((state) => state.session);
  const hasHydrated = useAuthStore((state) => state.hasHydrated);
  const logout = useAuthStore((state) => state.logout);
  const router = useRouter();

  const loginPath = scope === "staff" ? "/staff/login" : "/login";
  const isWrongScope = !session || session.scope !== scope;
  const isExpired = session ? isJwtExpired(session.token) : false;
  const isWrongRole =
    !isWrongScope && scope === "staff" && roles && session?.scope === "staff" && !roles.includes(session.role);

  useEffect(() => {
    if (!hasHydrated) return;
    if (isExpired) {
      logout();
      router.replace(loginPath);
      return;
    }
    if (isWrongScope) {
      router.replace(loginPath);
      return;
    }
    if (isWrongRole) {
      toast.error("You don't have permission to view that page");
      router.replace("/dashboard");
    }
  }, [hasHydrated, isExpired, isWrongScope, isWrongRole, loginPath, logout, router]);

  if (!hasHydrated || isWrongScope || isExpired || isWrongRole) {
    return <FullPageSpinner label="Checking your session…" />;
  }

  return <>{children}</>;
}
