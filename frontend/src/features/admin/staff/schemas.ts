import { z } from "zod";

export const createStaffUserSchema = z.object({
  username: z.string().min(3, "At least 3 characters").max(100),
  password: z.string().min(12, "At least 12 characters"),
  role: z.enum(["SUPPORT_AGENT", "SUPPORT_MANAGER", "ADMIN", "SECURITY_AGENT"]),
});
export type CreateStaffUserInput = z.infer<typeof createStaffUserSchema>;
