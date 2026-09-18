import { Compass } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/layout/Logo";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="px-6 py-5">
        <Logo on="content" />
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 pb-16 text-center">
        <Compass className="size-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Page not found</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          The page you&apos;re looking for doesn&apos;t exist, or may have moved.
        </p>
        <Link href="/" className="mt-2 text-sm font-medium text-primary hover:underline">
          Go back home
        </Link>
      </div>
    </div>
  );
}
