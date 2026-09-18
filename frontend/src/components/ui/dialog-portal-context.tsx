"use client";

import { createContext, useContext } from "react";

/**
 * The nearest ancestor <dialog> DOM node, if any - so Radix-portal-based
 * overlays (Select, DropdownMenu, ...) can render their floating content
 * *inside* that dialog's own DOM subtree instead of the default
 * document.body.
 *
 * Why this matters: a native <dialog> shown via showModal() (see
 * Dialog.tsx) is promoted to the browser's "top layer" - content
 * portaled to document.body while it's open paints BEHIND the dialog
 * regardless of z-index, a real, spec-defined interaction between the
 * top layer and body-portaled overlays, not a z-index bug to fight with
 * more z-index. Rendering the overlay inside the dialog element itself
 * keeps it in the same top-layer stacking context, so it paints
 * correctly on top - confirmed live: without this, a Select/DropdownMenu
 * opened from inside a Dialog rendered its content with the right ARIA
 * state and correct computed styles, but never visibly on screen.
 *
 * The node is carried as plain context state (set once the dialog
 * mounts), not a ref read during render - reading a ref's `.current`
 * value while rendering is unsafe (it can be stale and never triggers a
 * re-render of consumers when it changes).
 */
const DialogPortalContext = createContext<HTMLDialogElement | null>(null);

export const DialogPortalProvider = DialogPortalContext.Provider;

export function useDialogPortalContainer(): HTMLElement | undefined {
  return useContext(DialogPortalContext) ?? undefined;
}
