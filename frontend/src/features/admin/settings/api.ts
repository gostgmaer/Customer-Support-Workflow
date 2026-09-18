import { apiFetch } from "@/lib/api/client";
import type { SystemSetting } from "@/types/api";

export function listSettings() {
  return apiFetch<SystemSetting[]>("/api/v1/admin/settings");
}

export function updateSetting(key: string, value: unknown) {
  return apiFetch<SystemSetting>(`/api/v1/admin/settings/${key}`, { method: "PUT", body: { value } });
}

export function resetSetting(key: string) {
  return apiFetch<void>(`/api/v1/admin/settings/${key}`, { method: "DELETE" });
}
