"use client";

import { Wrench } from "lucide-react";

import type { Integration } from "@/types/api";

interface DiscoveredTool {
  name: string;
  description: string;
}

function isDiscoveredTool(value: unknown): value is DiscoveredTool {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).name === "string" &&
    typeof (value as Record<string, unknown>).description === "string"
  );
}

/**
 * Reads integration.config.discovered_tools directly - persisted by
 * app.integrations.health.test_connection's mcp branch on a successful
 * Test (spec: Phase 10.2, mirroring the openapi type's existing
 * config.spec_cache pattern). Visible immediately on load/after a Test,
 * not only for the lifetime of the mutation that fetched it.
 */
export function McpToolsPanel({ integration }: { integration: Integration }) {
  const raw = integration.config.discovered_tools;
  if (!Array.isArray(raw)) return null;
  const tools = raw.filter(isDiscoveredTool);
  if (tools.length === 0) return null;

  return (
    <div className="mt-3 rounded-md border border-border p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Wrench className="size-4 text-muted-foreground" aria-hidden="true" />
        Discovered tools ({tools.length})
      </div>
      <ul className="mt-2 space-y-1 text-sm">
        {tools.map((tool) => (
          <li key={tool.name} className="flex gap-2">
            <code className="shrink-0 rounded bg-accent px-1 py-0.5 text-xs">{tool.name}</code>
            {tool.description && <span className="text-muted-foreground">{tool.description}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
