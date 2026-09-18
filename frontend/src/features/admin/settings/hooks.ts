import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/store/toast-store";

import { listSettings, resetSetting, updateSetting } from "./api";

export function useSettings() {
  return useQuery({ queryKey: ["admin-settings"], queryFn: listSettings });
}

export function useUpdateSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) => updateSetting(key, value),
    onSuccess: (_data, variables) => {
      toast.success(`${variables.key} updated`);
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
    },
    onError: (error) => toast.error("Update failed", error instanceof Error ? error.message : undefined),
  });
}

export function useResetSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => resetSetting(key),
    onSuccess: (_data, key) => {
      toast.success(`${key} reset to default`);
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
    },
    onError: (error) => toast.error("Reset failed", error instanceof Error ? error.message : undefined),
  });
}
