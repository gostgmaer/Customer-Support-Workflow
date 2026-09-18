import { apiFetch } from "@/lib/api/client";
import type { Integration, IntegrationAuthType, IntegrationType } from "@/types/api";

export interface CreateIntegrationInput {
  name: string;
  type: IntegrationType;
  base_url: string;
  auth_type: IntegrationAuthType;
  credentials: Record<string, string>;
  config: Record<string, unknown>;
}

export function listIntegrations() {
  return apiFetch<Integration[]>("/api/v1/admin/integrations");
}

export function createIntegration(input: CreateIntegrationInput) {
  return apiFetch<Integration>("/api/v1/admin/integrations", { method: "POST", body: input });
}

export function updateIntegration(id: string, input: Partial<CreateIntegrationInput & { enabled: boolean }>) {
  return apiFetch<Integration>(`/api/v1/admin/integrations/${id}`, { method: "PUT", body: input });
}

export function deleteIntegration(id: string) {
  return apiFetch<void>(`/api/v1/admin/integrations/${id}`, { method: "DELETE" });
}

export function testIntegration(id: string) {
  return apiFetch<{ ok: boolean; message: string }>(`/api/v1/admin/integrations/${id}/test`, {
    method: "POST",
  });
}
