"use client";

import { LogOut, Menu } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { useLogout, useSession } from "@/features/auth/hooks";

import { Logo } from "./Logo";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function CustomerHeader() {
  const session = useSession();
  const logout = useLogout();

  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
        <Logo on="content" />
        {session?.scope === "customer" && (
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 sm:flex">
              <Avatar name={session.name} />
              <span className="text-sm font-medium text-foreground">{session.name}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={logout}>
              <LogOut className="size-4" aria-hidden="true" />
              Sign out
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}

function StaffLayout({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background md:flex">
      <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 items-center border-b border-border bg-card px-4 md:hidden">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
            className="-ml-2 rounded-md p-2 text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Menu className="size-5" aria-hidden="true" />
          </button>
          <div className="ml-2">
            <Logo on="content" />
          </div>
        </div>
        <TopBar />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session?.scope === "staff") {
    return <StaffLayout>{children}</StaffLayout>;
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <CustomerHeader />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
