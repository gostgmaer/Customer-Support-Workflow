"use client";

import { BookOpen, Inbox, LayoutDashboard, LogOut, Plug, Settings, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";

import { Avatar } from "@/components/ui/Avatar";
import { useLogout, useSession } from "@/features/auth/hooks";
import { useKnowledgeArticles } from "@/features/knowledge/hooks";
import { useTickets } from "@/features/tickets/hooks";
import { cn } from "@/lib/utils/cn";

import { Logo } from "./Logo";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: number;
}

const ADMIN_ITEMS: NavItem[] = [
  { href: "/admin/staff", label: "Staff", icon: Users },
  { href: "/admin/settings", label: "Settings", icon: Settings },
  { href: "/admin/integrations", label: "Integrations", icon: Plug },
];

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = pathname.startsWith(item.href);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex items-center justify-between gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-chrome-active text-chrome-foreground"
          : "text-chrome-muted hover:bg-chrome-hover hover:text-chrome-foreground"
      )}
    >
      <span className="flex items-center gap-2.5">
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {item.label}
      </span>
      {!!item.badge && (
        <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-xs tabular-nums text-chrome-muted">
          {item.badge}
        </span>
      )}
    </Link>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession();
  const logout = useLogout();
  const isAdmin = session?.scope === "staff" && session.role === "ADMIN";

  const tickets = useTickets(undefined);
  const articles = useKnowledgeArticles({ limit: 200 });

  const mainItems: NavItem[] = [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/tickets", label: "Tickets", icon: Inbox, badge: tickets.data?.length },
    { href: "/knowledge-base", label: "Knowledge Base", icon: BookOpen, badge: articles.data?.length },
  ];

  return (
    <div className="flex h-full flex-col bg-chrome text-chrome-foreground">
      <div className="flex h-14 items-center border-b border-chrome-border px-4">
        <Logo />
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-4" aria-label="Primary">
        <div>
          <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-chrome-muted">
            Navigation
          </p>
          <div className="space-y-0.5">
            {mainItems.map((item) => (
              <NavLink key={item.href} item={item} onNavigate={onNavigate} />
            ))}
          </div>
        </div>

        {isAdmin && (
          <div>
            <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-chrome-muted">
              Management
            </p>
            <div className="space-y-0.5">
              {ADMIN_ITEMS.map((item) => (
                <NavLink key={item.href} item={item} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        )}
      </nav>

      {session?.scope === "staff" && (
        <div className="border-t border-chrome-border p-3">
          <div className="flex items-center gap-2.5 rounded-md px-1 py-1.5">
            <Avatar name={session.id} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-chrome-foreground">{session.id}</p>
              <p className="truncate text-xs text-chrome-muted">{session.role}</p>
            </div>
            <button
              type="button"
              onClick={logout}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-chrome-muted hover:bg-chrome-hover hover:text-chrome-foreground"
            >
              <LogOut className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ mobileOpen, onClose }: { mobileOpen: boolean; onClose: () => void }) {
  return (
    <>
      {/* Desktop: persistent rail */}
      <aside className="hidden w-64 shrink-0 border-r border-chrome-border md:block">
        <div className="fixed h-screen w-64">
          <SidebarContent />
        </div>
      </aside>

      {/* Mobile: slide-in drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={onClose}
          />
          <div className="absolute inset-y-0 left-0 w-72 bg-chrome shadow-lg">
            <button
              type="button"
              onClick={onClose}
              aria-label="Close menu"
              className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-chrome-muted hover:bg-chrome-hover hover:text-chrome-foreground"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
            <SidebarContent onNavigate={onClose} />
          </div>
        </div>
      )}
    </>
  );
}
