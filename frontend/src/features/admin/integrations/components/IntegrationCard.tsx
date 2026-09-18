"use client";

import { Bug, Cable, FileJson, Plug, ShoppingCart, Trash2, Wrench, Zap } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import type { Integration } from "@/types/api";

import { useDeleteIntegration, useTestIntegration, useToggleIntegration } from "../hooks";
import { INTEGRATION_TYPE_META } from "../metadata";
import { McpToolsPanel } from "./McpToolsPanel";

const ICONS = {
  jira: Bug,
  woocommerce: ShoppingCart,
  smtp: Zap,
  custom: Wrench,
  mcp: Cable,
  openapi: FileJson,
} as const;

export function IntegrationCard({ integration }: { integration: Integration }) {
  const toggleIntegration = useToggleIntegration();
  const testIntegration = useTestIntegration();
  const deleteIntegration = useDeleteIntegration();
  const Icon = ICONS[integration.type] ?? Plug;

  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-4 py-4">
        <div className="flex gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <Icon className="size-4" aria-hidden="true" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <p className="font-medium">{integration.name}</p>
              <Badge variant={integration.enabled ? "success" : "default"}>
                {integration.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {INTEGRATION_TYPE_META[integration.type]?.label ?? integration.type} · {integration.base_url}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => testIntegration.mutate(integration.id)}
            isLoading={testIntegration.isPending}
          >
            Test
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => toggleIntegration.mutate({ id: integration.id, enabled: !integration.enabled })}
            isLoading={toggleIntegration.isPending}
          >
            {integration.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete ${integration.name}`}
            onClick={() => {
              if (confirm(`Remove the "${integration.name}" integration? This can't be undone.`)) {
                deleteIntegration.mutate(integration.id);
              }
            }}
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </CardContent>
      {integration.type === "mcp" && (
        <CardContent className="pt-0">
          <McpToolsPanel integration={integration} />
        </CardContent>
      )}
    </Card>
  );
}
