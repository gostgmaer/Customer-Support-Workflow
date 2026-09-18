"use client";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { SettingRow } from "@/features/admin/settings/components/SettingRow";
import { useSettings } from "@/features/admin/settings/hooks";
import { getErrorMessage } from "@/lib/api/get-error-message";

function SettingsContent() {
  const settings = useSettings();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Runtime settings</h1>
        <p className="text-sm text-muted-foreground">
          Changes apply immediately, per tenant, without a redeploy. An &quot;override&quot; value takes
          permanent precedence over the environment variable until you reset it.
        </p>
      </div>

      {settings.isError && <Alert variant="error">{getErrorMessage(settings.error)}</Alert>}

      {settings.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : (
        <Card className="overflow-hidden py-0">
          {settings.data?.map((setting) => (
            <SettingRow key={setting.key} setting={setting} />
          ))}
        </Card>
      )}
    </div>
  );
}

export default function AdminSettingsPage() {
  return (
    <AuthGuard scope="staff" roles={["ADMIN"]}>
      <AppShell>
        <SettingsContent />
      </AppShell>
    </AuthGuard>
  );
}
