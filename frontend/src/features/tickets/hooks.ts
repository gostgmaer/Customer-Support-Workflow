import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/store/toast-store";

import {
  approveTicket,
  createJiraIssueForTicket,
  getTicket,
  getTicketTrace,
  listTickets,
  lookupWooCommerceOrder,
  rejectTicket,
} from "./api";

export function useTickets(status: string | undefined) {
  return useQuery({
    queryKey: ["tickets", { status }],
    queryFn: () => listTickets({ status, limit: 100 }),
    refetchInterval: 15_000,
  });
}

export function useTicket(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => getTicket(ticketId),
  });
}

export function useTicketTrace(ticketId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["ticket-trace", ticketId],
    queryFn: () => getTicketTrace(ticketId),
    enabled,
  });
}

export function useApproveTicket(ticketId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowRunId,
      argumentsOverride,
    }: {
      workflowRunId: string;
      argumentsOverride?: Record<string, string>;
    }) => approveTicket(ticketId, workflowRunId, argumentsOverride),
    onSuccess: () => {
      toast.success("Ticket approved");
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
    onError: (error) => toast.error("Couldn't approve ticket", error instanceof Error ? error.message : undefined),
  });
}

export function useRejectTicket(ticketId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workflowRunId, reason }: { workflowRunId: string; reason: string }) =>
      rejectTicket(ticketId, workflowRunId, reason),
    onSuccess: () => {
      toast.success("Ticket rejected");
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
    onError: (error) => toast.error("Couldn't reject ticket", error instanceof Error ? error.message : undefined),
  });
}

export function useCreateJiraIssue(ticketId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => createJiraIssueForTicket(ticketId),
    onSuccess: (ticket) => {
      toast.success("JIRA issue created", ticket.external_ref ?? undefined);
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
    onError: (error) =>
      toast.error("Couldn't create JIRA issue", error instanceof Error ? error.message : undefined),
  });
}

export function useWooCommerceLookup() {
  return useMutation({
    mutationFn: (orderNumber: string) => lookupWooCommerceOrder(orderNumber),
    onError: (error) => toast.error("Lookup failed", error instanceof Error ? error.message : undefined),
  });
}
