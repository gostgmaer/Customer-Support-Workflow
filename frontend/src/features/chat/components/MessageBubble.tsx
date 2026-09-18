import { format } from "date-fns";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

import { cn } from "@/lib/utils/cn";
import type { Message } from "@/types/api";

/** react-markdown parses to a React element tree - it never injects raw
 * HTML (no dangerouslySetInnerHTML) unless a rehype-raw-style plugin is
 * added, which this deliberately never does. The content is still raw
 * customer input / LLM output either way, so this stays exactly as safe
 * as the plain-text rendering it replaces (see repository.md security
 * guidance) while actually rendering the markdown assistant responses
 * commonly contain (headings, bold, lists, links). */
function markdownComponents(isCustomer: boolean): Components {
  const linkClass = isCustomer
    ? "underline decoration-primary-foreground/50 hover:decoration-primary-foreground"
    : "text-primary underline decoration-primary/40 hover:decoration-primary";
  const codeClass = isCustomer
    ? "rounded bg-primary-foreground/15 px-1 py-0.5 font-mono text-[0.85em]"
    : "rounded bg-foreground/10 px-1 py-0.5 font-mono text-[0.85em]";

  return {
    p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
    a: ({ children, href }) => (
      <a href={href} target="_blank" rel="noreferrer" className={linkClass}>
        {children}
      </a>
    ),
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0">{children}</ul>,
    ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    h1: ({ children }) => <h3 className="mb-1.5 mt-2 text-[1.05em] font-semibold first:mt-0">{children}</h3>,
    h2: ({ children }) => <h3 className="mb-1.5 mt-2 text-[1.05em] font-semibold first:mt-0">{children}</h3>,
    h3: ({ children }) => <h4 className="mb-1 mt-2 font-semibold first:mt-0">{children}</h4>,
    code: ({ children }) => <code className={codeClass}>{children}</code>,
    pre: ({ children }) => (
      <pre className="mb-2 overflow-x-auto rounded-md bg-foreground/10 p-2.5 text-[0.85em] last:mb-0">
        {children}
      </pre>
    ),
    blockquote: ({ children }) => (
      <blockquote className="mb-2 border-l-2 border-current/30 pl-3 italic opacity-90 last:mb-0">
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-2 border-current/20" />,
  };
}

export function MessageBubble({ message }: { message: Message }) {
  const isCustomer = message.role === "customer";
  const isSystem = message.role === "system" || message.role === "human_agent";

  if (isSystem) {
    return (
      <div className="my-2 text-center text-xs text-muted-foreground" role="status">
        {message.content}
      </div>
    );
  }

  return (
    <div className={cn("flex", isCustomer ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm break-words",
          isCustomer
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm bg-secondary text-secondary-foreground"
        )}
      >
        <div className="[&>*:last-child]:mb-0">
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents(isCustomer)}>
            {message.content}
          </Markdown>
        </div>
        <div
          className={cn(
            "mt-1 text-[11px] opacity-70",
            isCustomer ? "text-primary-foreground" : "text-muted-foreground"
          )}
        >
          {format(new Date(message.created_at), "h:mm a")}
        </div>
      </div>
    </div>
  );
}
