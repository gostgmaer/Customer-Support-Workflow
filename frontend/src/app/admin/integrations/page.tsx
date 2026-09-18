"use client";

import { Plug, Plus } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { CreateIntegrationDialog } from "@/features/admin/integrations/components/CreateIntegrationDialog";
import { IntegrationCard } from "@/features/admin/integrations/components/IntegrationCard";
import { useIntegrations } from "@/features/admin/integrations/hooks";

function IntegrationsContent() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const integrations = useIntegrations();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Integrations</h1>
          <p className="text-sm text-muted-foreground">
            Connect JIRA, WooCommerce, email, or any other REST API.
          </p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <Plus className="size-4" aria-hidden="true" />
          Add integration
        </Button>
      </div>

      {integrations.isError && <ApiErrorState error={integrations.error} />}

      {integrations.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : integrations.data && integrations.data.length > 0 ? (
        <div className="space-y-3">
          {integrations.data.map((integration) => (
            <IntegrationCard key={integration.id} integration={integration} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Plug}
          title="No integrations connected"
          description="Add JIRA to auto-file escalations, SMTP to notify customers, or WooCommerce to look up orders."
          action={
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="size-4" aria-hidden="true" />
              Add integration
            </Button>
          }
        />
      )}

      <CreateIntegrationDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}

export default function IntegrationsPage() {
  return (
    <AuthGuard scope="staff" roles={["ADMIN"]}>
      <AppShell>
        <IntegrationsContent />
      </AppShell>
    </AuthGuard>
  );
}
