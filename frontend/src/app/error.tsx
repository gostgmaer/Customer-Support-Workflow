"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/Button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // No error-tracking service wired up yet - at minimum this keeps the
    // real error visible in the browser console, not just the generic
    // message shown below.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="px-6 py-5">
        <Logo on="content" />
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 pb-16 text-center">
        <AlertTriangle className="size-8 text-danger" aria-hidden="true" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Something went wrong</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          An unexpected error occurred. You can try again, or head back home.
        </p>
        <div className="mt-2 flex items-center gap-4">
          <Button variant="outline" onClick={reset}>
            Try again
          </Button>
          <Link href="/" className="text-sm font-medium text-primary hover:underline">
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}
