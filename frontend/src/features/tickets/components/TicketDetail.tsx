"use client";

import { format } from "date-fns";
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  ExternalLink,
  ListChecks,
  MessageSquareText,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";

import { useApproveTicket, useCreateJiraIssue, useRejectTicket } from "../hooks";
import type { SupportTicket } from "@/types/api";

import { AgentTracePanel } from "./AgentTracePanel";
import { PendingCallPanel } from "./PendingCallPanel";
import { RejectTicketDialog } from "./RejectTicketDialog";
import { WooCommerceLookupPanel } from "./WooCommerceLookupPanel";

function DetailField({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 whitespace-pre-wrap text-sm text-foreground">{value}</dd>
    </div>
  );
}

function TagList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
            {item}
          </span>
        ))}
      </dd>
    </div>
  );
}

export function TicketDetail({ ticket }: { ticket: SupportTicket }) {
  const [rejectOpen, setRejectOpen] = useState(false);
  // Only fields staff actually touched - sent as the approve override so
  // an untouched field keeps its original (correctly-typed) proposed
  // value rather than being coerced through this text-input UI.
  const [argEdits, setArgEdits] = useState<Record<string, string>>({});
  const approve = useApproveTicket(ticket.id);
  const reject = useRejectTicket(ticket.id);
  const createJiraIssue = useCreateJiraIssue(ticket.id);

  const canAct = ticket.status === "open" && !!ticket.workflow_run_id;
  const hasActivity =
    ticket.actions_taken.length > 0 || ticket.tools_used.length > 0 || ticket.relevant_documents.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            {ticket.summary || "Support ticket"}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Opened {format(new Date(ticket.created_at), "MMM d, yyyy 'at' h:mm a")}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <PriorityBadge priority={ticket.priority} />
          <StatusBadge status={ticket.status} />
        </div>
      </div>

      {canAct && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning-bg px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-warning">
            <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
            Awaiting your decision before this can proceed.
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" size="sm" onClick={() => setRejectOpen(true)} isLoading={reject.isPending}>
              <XCircle className="size-4" aria-hidden="true" />
              Reject
            </Button>
            <Button
              size="sm"
              onClick={() =>
                approve.mutate({
                  workflowRunId: ticket.workflow_run_id as string,
                  argumentsOverride: Object.keys(argEdits).length > 0 ? argEdits : undefined,
                })
              }
              isLoading={approve.isPending}
            >
              <CheckCircle2 className="size-4" aria-hidden="true" />
              Approve
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {ticket.customer_problem && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <MessageSquareText className="size-4 text-muted-foreground" aria-hidden="true" />
                  Customer problem
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm text-foreground">{ticket.customer_problem}</p>
              </CardContent>
            </Card>
          )}

          {(ticket.reason_for_escalation || ticket.recommended_next_action) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
                  AI assessment
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <DetailField label="Reason for escalation" value={ticket.reason_for_escalation} />
                <DetailField label="Recommended next action" value={ticket.recommended_next_action} />
              </CardContent>
            </Card>
          )}

          {hasActivity && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <ListChecks className="size-4 text-muted-foreground" aria-hidden="true" />
                  Activity
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-3">
                <TagList label="Actions taken" items={ticket.actions_taken} />
                <TagList label="Tools used" items={ticket.tools_used} />
                <TagList label="Relevant documents" items={ticket.relevant_documents} />
              </CardContent>
            </Card>
          )}

          {ticket.pending_call && (
            <PendingCallPanel
              pendingCall={ticket.pending_call}
              values={Object.fromEntries(
                Object.entries(ticket.pending_call.arguments).map(([key, value]) => [
                  key,
                  argEdits[key] ?? String(value ?? ""),
                ])
              )}
              onChange={(key, value) => setArgEdits((prev) => ({ ...prev, [key]: value }))}
              disabled={!canAct}
            />
          )}

          {ticket.execution_result && (
            <div className="rounded-md border border-border p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Execution result
              </p>
              <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap wrap-break-word text-xs text-foreground">
                {JSON.stringify(ticket.execution_result, null, 2)}
              </pre>
            </div>
          )}

          <AgentTracePanel ticketId={ticket.id} hasWorkflowRun={!!ticket.workflow_run_id} />
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <DetailField label="Intent" value={ticket.intent.replace(/_/g, " ")} />
              <DetailField label="Approved / rejected by" value={ticket.approved_by ?? ""} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Bug className="size-4 text-muted-foreground" aria-hidden="true" />
                JIRA
              </CardTitle>
            </CardHeader>
            <CardContent>
              {ticket.external_ref ? (
                <a
                  href={ticket.external_url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                >
                  {ticket.external_ref}
                  <ExternalLink className="size-3" aria-hidden="true" />
                </a>
              ) : (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-muted-foreground">Not linked</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => createJiraIssue.mutate()}
                    isLoading={createJiraIssue.isPending}
                  >
                    Create
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <WooCommerceLookupPanel />
        </div>
      </div>

      <RejectTicketDialog
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        isSubmitting={reject.isPending}
        onConfirm={(reason) => {
          reject.mutate(
            { workflowRunId: ticket.workflow_run_id as string, reason },
            { onSuccess: () => setRejectOpen(false) }
          );
        }}
      />
    </div>
  );
}
