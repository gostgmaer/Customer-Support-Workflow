import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { Logo } from "@/components/layout/Logo";

export function AuthLayout({
  title,
  description,
  eyebrow,
  highlights = [],
  children,
}: {
  title: string;
  description?: string;
  eyebrow?: string;
  highlights?: string[];
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <div className="hidden w-[42%] flex-col justify-between bg-chrome p-10 text-chrome-foreground lg:flex xl:w-1/2">
        <Logo />
        {eyebrow && (
          <div className="max-w-sm space-y-6">
            <p className="text-2xl font-semibold leading-snug text-chrome-foreground">{eyebrow}</p>
            {highlights.length > 0 && (
              <ul className="space-y-3">
                {highlights.map((item) => (
                  <li key={item} className="flex items-start gap-2.5 text-sm text-chrome-muted">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <p className="text-xs text-chrome-muted">Production-grade AI customer support platform</p>
      </div>

      <div className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo on="content" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
          {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}
