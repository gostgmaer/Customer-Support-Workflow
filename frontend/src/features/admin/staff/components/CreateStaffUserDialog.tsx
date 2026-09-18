"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FieldError, Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { getErrorMessage } from "@/lib/api/get-error-message";
import type { StaffRole } from "@/types/api";

import { useCreateStaffUser } from "../hooks";
import { type CreateStaffUserInput, createStaffUserSchema } from "../schemas";

const ROLES: StaffRole[] = ["SUPPORT_AGENT", "SUPPORT_MANAGER", "SECURITY_AGENT", "ADMIN"];

export function CreateStaffUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateStaffUserInput>({
    resolver: zodResolver(createStaffUserSchema),
    defaultValues: { role: "SUPPORT_AGENT" },
  });
  const createStaffUserMutation = useCreateStaffUser();

  const close = () => {
    reset();
    onClose();
  };

  return (
    <Dialog open={open} onClose={close} title="Add a staff account" description="Creates a new account in your tenant.">
      <form
        onSubmit={handleSubmit((values) =>
          createStaffUserMutation.mutate(values, { onSuccess: close })
        )}
        className="space-y-4"
        noValidate
      >
        {createStaffUserMutation.isError && (
          <Alert variant="error">{getErrorMessage(createStaffUserMutation.error)}</Alert>
        )}

        <div>
          <Label htmlFor="username">Username</Label>
          <Input id="username" invalid={!!errors.username} {...register("username")} />
          <FieldError>{errors.username?.message}</FieldError>
        </div>

        <div>
          <Label htmlFor="password">Temporary password</Label>
          <Input id="password" type="password" invalid={!!errors.password} {...register("password")} />
          <FieldError>{errors.password?.message}</FieldError>
        </div>

        <div>
          <Label htmlFor="role">Role</Label>
          <select
            id="role"
            {...register("role")}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" isLoading={createStaffUserMutation.isPending}>
            Create account
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
