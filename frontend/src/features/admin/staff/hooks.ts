import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/store/toast-store";

import { createStaffUser, listStaffUsers } from "./api";
import type { CreateStaffUserInput } from "./schemas";

export function useStaffUsers() {
  return useQuery({ queryKey: ["staff-users"], queryFn: listStaffUsers });
}

export function useCreateStaffUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateStaffUserInput) => createStaffUser(input),
    onSuccess: (user) => {
      toast.success(`${user.username} created`, `Role: ${user.role}`);
      queryClient.invalidateQueries({ queryKey: ["staff-users"] });
    },
  });
}
