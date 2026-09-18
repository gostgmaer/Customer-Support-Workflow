"use client";

import { ArrowRight, Headset, MessageCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Logo } from "@/components/layout/Logo";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { useSession } from "@/features/auth/hooks";
import { useAuthStore } from "@/store/auth-store";

export default function HomePage() {
  const session = useSession();
  const hasHydrated = useAuthStore((state) => state.hasHydrated);
  const router = useRouter();

  useEffect(() => {
    if (!hasHydrated) return;
    if (session?.scope === "customer") router.replace("/chat");
    if (session?.scope === "staff") router.replace("/tickets");
  }, [hasHydrated, session, router]);

  if (!hasHydrated || session) return <FullPageSpinner />;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="px-6 py-5">
        <Logo on="content" />
      </header>

      <div className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-2xl text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            How would you like to sign in?
          </h1>
          <p className="mt-3 text-muted-foreground">
            One platform for customer conversations and the team that handles them.
          </p>

          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            <Link
              href="/login"
              className="group flex flex-col items-start gap-3 rounded-xl border border-border bg-card p-6 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className="flex size-11 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <MessageCircle className="size-5" aria-hidden="true" />
              </span>
              <div>
                <p className="font-semibold text-foreground">I&apos;m a customer</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Get help from our AI assistant, day or night.
                </p>
              </div>
              <span className="mt-1 inline-flex items-center gap-1 text-sm font-medium text-primary">
                Continue
                <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </span>
            </Link>

            <Link
              href="/staff/login"
              className="group flex flex-col items-start gap-3 rounded-xl border border-border bg-card p-6 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className="flex size-11 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <Headset className="size-5" aria-hidden="true" />
              </span>
              <div>
                <p className="font-semibold text-foreground">I&apos;m support staff</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Review the ticket queue and act on escalations.
                </p>
              </div>
              <span className="mt-1 inline-flex items-center gap-1 text-sm font-medium text-primary">
                Continue
                <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
