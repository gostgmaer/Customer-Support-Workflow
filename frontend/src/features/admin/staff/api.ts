import { apiFetch } from "@/lib/api/client";
import type { StaffRole, StaffUser } from "@/types/api";

export function listStaffUsers() {
  return apiFetch<StaffUser[]>("/api/v1/staff/users");
}

export function createStaffUser(input: { username: string; password: string; role: StaffRole }) {
  return apiFetch<StaffUser>("/api/v1/staff/users", { method: "POST", body: input });
}
