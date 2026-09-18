"use client";

import { UserPlus } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Button } from "@/components/ui/Button";
import { CreateStaffUserDialog } from "@/features/admin/staff/components/CreateStaffUserDialog";
import { StaffUserTable } from "@/features/admin/staff/components/StaffUserTable";
import { useStaffUsers } from "@/features/admin/staff/hooks";

function StaffAdminContent() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const staffUsers = useStaffUsers();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Staff accounts</h1>
          <p className="text-sm text-muted-foreground">Manage who can access the ticket queue.</p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <UserPlus className="size-4" aria-hidden="true" />
          Add staff
        </Button>
      </div>

      {staffUsers.isError && <ApiErrorState error={staffUsers.error} />}

      <StaffUserTable users={staffUsers.data} isLoading={staffUsers.isLoading} />

      <CreateStaffUserDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  );
}

export default function StaffAdminPage() {
  return (
    <AuthGuard scope="staff" roles={["ADMIN"]}>
      <AppShell>
        <StaffAdminContent />
      </AppShell>
    </AuthGuard>
  );
}
