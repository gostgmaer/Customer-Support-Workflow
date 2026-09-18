"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

type ThemeOverride = "light" | "dark" | null;

function readStoredTheme(): ThemeOverride {
  try {
    const value = localStorage.getItem("theme");
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function subscribeToStorage(callback: () => void) {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function getServerOverride(): ThemeOverride {
  return null;
}

function getSystemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function getServerPrefersDark(): boolean {
  return false;
}

function subscribeToSystemScheme(callback: () => void) {
  const mql = window.matchMedia("(prefers-color-scheme: dark)");
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

/** Explicit override on top of the OS preference (see globals.css's dual
 * `:root[data-theme]` / `@media (prefers-color-scheme)` selectors) -
 * persisted so it survives a reload, applied instantly on the next load
 * via the inline script in app/layout.tsx to avoid a whole-page flash.
 *
 * Reads localStorage/matchMedia through useSyncExternalStore rather than
 * an effect + setState: both are browser-only APIs the server can't see,
 * and this is React's own supported way to reconcile that without a
 * cascading re-render or a hydration mismatch. The server snapshot always
 * reports "light, no override," so this button's icon can very briefly
 * mismatch an OS-dark page background until the client snapshot takes
 * over on mount - a cosmetic one-frame flash on the icon only, distinct
 * from (and much smaller than) the whole-page flash the layout script
 * already prevents.
 */
export function ThemeToggle() {
  const override = useSyncExternalStore(subscribeToStorage, readStoredTheme, getServerOverride);
  const systemPrefersDark = useSyncExternalStore(
    subscribeToSystemScheme,
    getSystemPrefersDark,
    getServerPrefersDark
  );
  const isDark = (override ?? (systemPrefersDark ? "dark" : "light")) === "dark";

  const toggle = () => {
    const next: ThemeOverride = isDark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Private browsing / storage disabled - the toggle still works for
      // this page load via the DOM attribute, it just won't persist.
    }
    // localStorage.setItem in the SAME tab does not fire a "storage"
    // event (that's cross-tab only) - dispatch one so this tab's own
    // useSyncExternalStore subscription re-renders immediately too.
    window.dispatchEvent(new Event("storage"));
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    >
      {isDark ? <Sun className="size-4.5" aria-hidden="true" /> : <Moon className="size-4.5" aria-hidden="true" />}
    </button>
  );
}
