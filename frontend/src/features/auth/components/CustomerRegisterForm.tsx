"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useForm } from "react-hook-form";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { FieldError, Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { getErrorMessage } from "@/lib/api/get-error-message";

import { useCustomerRegister } from "../hooks";
import { type CustomerRegisterInput, customerRegisterSchema } from "../schemas";

export function CustomerRegisterForm() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CustomerRegisterInput>({ resolver: zodResolver(customerRegisterSchema) });
  const registerCustomer = useCustomerRegister();

  return (
    <form
      onSubmit={handleSubmit((values) => registerCustomer.mutate(values))}
      className="space-y-4"
      noValidate
    >
      {registerCustomer.isError && <Alert variant="error">{getErrorMessage(registerCustomer.error)}</Alert>}

      <div>
        <Label htmlFor="full_name">Full name</Label>
        <Input id="full_name" autoComplete="name" invalid={!!errors.full_name} {...register("full_name")} />
        <FieldError>{errors.full_name?.message}</FieldError>
      </div>

      <div>
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          invalid={!!errors.email}
          {...register("email")}
        />
        <FieldError>{errors.email?.message}</FieldError>
      </div>

      <div>
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          invalid={!!errors.password}
          {...register("password")}
        />
        <FieldError>{errors.password?.message}</FieldError>
      </div>

      <Button type="submit" className="w-full" isLoading={registerCustomer.isPending}>
        Create account
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
