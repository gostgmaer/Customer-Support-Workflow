import { apiFetch } from "@/lib/api/client";
import type { SupportTicket, TicketTrace, WooCommerceOrderSummary } from "@/types/api";

export function listTickets(params: { status?: string; limit?: number; offset?: number } = {}) {
  return apiFetch<SupportTicket[]>("/api/v1/support/tickets", { query: params });
}

export function getTicket(ticketId: string) {
  return apiFetch<SupportTicket>(`/api/v1/support/tickets/${ticketId}`);
}

export function getTicketTrace(ticketId: string) {
  return apiFetch<TicketTrace>(`/api/v1/support/tickets/${ticketId}/trace`);
}

export function approveTicket(
  ticketId: string,
  workflowRunId: string,
  argumentsOverride?: Record<string, string>
) {
  return apiFetch<SupportTicket>(`/api/v1/support/tickets/${ticketId}/approve`, {
    method: "POST",
    body: { workflow_run_id: workflowRunId, arguments: argumentsOverride },
  });
}

export function rejectTicket(ticketId: string, workflowRunId: string, reason: string) {
  return apiFetch<SupportTicket>(`/api/v1/support/tickets/${ticketId}/reject`, {
    method: "POST",
    body: { workflow_run_id: workflowRunId, reason },
  });
}

export function createJiraIssueForTicket(ticketId: string) {
  return apiFetch<SupportTicket>(`/api/v1/support/tickets/${ticketId}/jira`, { method: "POST" });
}

export function lookupWooCommerceOrder(orderNumber: string) {
  return apiFetch<WooCommerceOrderSummary | null>("/api/v1/support/integrations/woocommerce/lookup", {
    method: "POST",
    body: { order_number: orderNumber },
  });
}
