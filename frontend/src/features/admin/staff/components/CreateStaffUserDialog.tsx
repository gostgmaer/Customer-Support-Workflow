"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FieldError, Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
    control,
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
          <Controller
            control={control}
            name="role"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="role" className="h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      {role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
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
