import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/store/toast-store";

import {
  type CreateIntegrationInput,
  createIntegration,
  deleteIntegration,
  listIntegrations,
  testIntegration,
  updateIntegration,
} from "./api";

export function useIntegrations() {
  return useQuery({ queryKey: ["integrations"], queryFn: listIntegrations });
}

export function useCreateIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateIntegrationInput) => createIntegration(input),
    onSuccess: (integration) => {
      toast.success(`${integration.name} connected`);
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
}

export function useToggleIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updateIntegration(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
}

export function useDeleteIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteIntegration(id),
    onSuccess: () => {
      toast.success("Integration removed");
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
}

export function useTestIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => testIntegration(id),
    onSuccess: (result) => {
      if (result.ok) toast.success("Connection OK", result.message);
      else toast.error("Connection failed", result.message);
      // A successful Test can persist discovered data into config
      // (discovered_tools for mcp, spec_cache for openapi - spec: Phase
      // 10.2) - without this, that mutation was invisible in the UI
      // until a manual page reload.
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
    onError: (error) => toast.error("Test failed", error instanceof Error ? error.message : undefined),
  });
}
