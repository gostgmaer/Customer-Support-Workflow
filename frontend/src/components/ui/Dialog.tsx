"use client";

import { X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { DialogPortalProvider } from "@/components/ui/dialog-portal-context";
import { cn } from "@/lib/utils/cn";

/**
 * Built on the native <dialog> element rather than a hand-rolled focus
 * trap: the browser already gives us modal semantics, Escape-to-close,
 * and correct focus management for free (see checklists.md - accessible
 * modal without extra dependencies).
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [dialogNode, setDialogNode] = useState<HTMLDialogElement | null>(null);

  const setRefs = useCallback((node: HTMLDialogElement | null) => {
    ref.current = node;
    setDialogNode(node);
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  return (
    <dialog
      ref={setRefs}
      onClose={onClose}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      aria-labelledby="dialog-title"
      className={cn(
        "m-auto w-full max-w-md rounded-lg border border-border bg-card p-0 text-card-foreground shadow-xl backdrop:bg-black/50",
        className
      )}
    >
      <div className="flex items-start justify-between border-b border-border px-5 py-4">
        <div>
          <h2 id="dialog-title" className="text-base font-semibold">
            {title}
          </h2>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div className="px-5 py-4">
        <DialogPortalProvider value={dialogNode}>{children}</DialogPortalProvider>
      </div>
    </dialog>
  );
}
