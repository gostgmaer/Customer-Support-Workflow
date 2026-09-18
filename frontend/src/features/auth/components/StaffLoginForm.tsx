"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { FieldError, Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { getErrorMessage } from "@/lib/api/get-error-message";

import { useStaffLogin } from "../hooks";
import { type StaffLoginInput, staffLoginSchema } from "../schemas";

export function StaffLoginForm() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<StaffLoginInput>({ resolver: zodResolver(staffLoginSchema) });
  const login = useStaffLogin();

  return (
    <form
      onSubmit={handleSubmit((values) => login.mutate(values))}
      className="space-y-4"
      noValidate
    >
      {login.isError && <Alert variant="error">{getErrorMessage(login.error)}</Alert>}

      <div>
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          autoComplete="username"
          invalid={!!errors.username}
          {...register("username")}
        />
        <FieldError>{errors.username?.message}</FieldError>
      </div>

      <div>
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          invalid={!!errors.password}
          {...register("password")}
        />
        <FieldError>{errors.password?.message}</FieldError>
      </div>

      <Button type="submit" className="w-full" isLoading={login.isPending}>
        Sign in
      </Button>
    </form>
  );
}
