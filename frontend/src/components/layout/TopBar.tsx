"use client";

import { Bell, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useTickets } from "@/features/tickets/hooks";

import { ThemeToggle } from "./ThemeToggle";

const PAGE_TITLES: { prefix: string; label: string }[] = [
  { prefix: "/dashboard", label: "Dashboard" },
  { prefix: "/knowledge-base", label: "Knowledge Base" },
  { prefix: "/tickets", label: "Tickets" },
  { prefix: "/admin/staff", label: "Staff" },
  { prefix: "/admin/settings", label: "Settings" },
  { prefix: "/admin/integrations", label: "Integrations" },
];

function pageTitle(pathname: string): string {
  return PAGE_TITLES.find((p) => pathname.startsWith(p.prefix))?.label ?? "Support Console";
}

export function TopBar() {
  const pathname = usePathname();
  const tickets = useTickets(undefined);
  const needsAttention = (tickets.data ?? []).filter(
    (t) => t.status === "open" || t.status === "awaiting_approval"
  ).length;

  return (
    <header className="hidden h-14 shrink-0 items-center justify-between border-b border-border bg-card px-6 md:flex">
      <p className="text-sm font-medium text-foreground">{pageTitle(pathname)}</p>

      <div className="flex items-center gap-1">
        <Link
          href="/knowledge-base"
          aria-label="Search the knowledge base"
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <Search className="size-4.5" aria-hidden="true" />
        </Link>

        <Link
          href="/tickets"
          aria-label={`${needsAttention} tickets need attention`}
          className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <Bell className="size-4.5" aria-hidden="true" />
          {needsAttention > 0 && (
            <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-danger text-[10px] font-semibold text-danger-foreground">
              {needsAttention > 9 ? "9+" : needsAttention}
            </span>
          )}
        </Link>

        <ThemeToggle />
      </div>
    </header>
  );
}
