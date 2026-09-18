import { z } from "zod";

export const customerLoginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
export type CustomerLoginInput = z.infer<typeof customerLoginSchema>;

export const customerRegisterSchema = z.object({
  full_name: z.string().min(1, "Name is required").max(200),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(8, "Must be at least 8 characters"),
});
export type CustomerRegisterInput = z.infer<typeof customerRegisterSchema>;

export const staffLoginSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});
export type StaffLoginInput = z.infer<typeof staffLoginSchema>;
