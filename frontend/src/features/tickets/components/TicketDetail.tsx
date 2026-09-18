"use client";

import { format } from "date-fns";
import { Bug, CheckCircle2, ExternalLink, XCircle } from "lucide-react";
import { useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";

import { useApproveTicket, useCreateJiraIssue, useRejectTicket } from "../hooks";
import type { SupportTicket } from "@/types/api";

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

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{ticket.summary || "Support ticket"}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Opened {format(new Date(ticket.created_at), "MMM d, yyyy 'at' h:mm a")}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <PriorityBadge priority={ticket.priority} />
          <StatusBadge status={ticket.status} />
        </div>
      </CardHeader>

      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          <DetailField label="Intent" value={ticket.intent.replace(/_/g, " ")} />
          <DetailField label="Approved / rejected by" value={ticket.approved_by ?? ""} />
          <DetailField label="Customer problem" value={ticket.customer_problem} />
          <DetailField label="Reason for escalation" value={ticket.reason_for_escalation} />
          <DetailField label="Recommended next action" value={ticket.recommended_next_action} />
        </dl>

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <TagList label="Actions taken" items={ticket.actions_taken} />
          <TagList label="Tools used" items={ticket.tools_used} />
          <TagList label="Relevant documents" items={ticket.relevant_documents} />
        </div>

        <div className="mt-4 flex items-center justify-between gap-4 rounded-md border border-border p-4">
          <div className="flex items-center gap-2 text-sm">
            <Bug className="size-4 text-muted-foreground" aria-hidden="true" />
            {ticket.external_ref ? (
              <a
                href={ticket.external_url ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
              >
                {ticket.external_ref}
                <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            ) : (
              <span className="text-muted-foreground">Not linked to a JIRA issue</span>
            )}
          </div>
          {!ticket.external_ref && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => createJiraIssue.mutate()}
              isLoading={createJiraIssue.isPending}
            >
              Create in JIRA
            </Button>
          )}
        </div>

        <div className="mt-4">
          <WooCommerceLookupPanel />
        </div>

        {ticket.pending_call && (
          <div className="mt-4">
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
          </div>
        )}

        {ticket.execution_result && (
          <div className="mt-4 rounded-md border border-border p-4">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Execution result
            </dt>
            <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-words text-xs text-foreground">
              {JSON.stringify(ticket.execution_result, null, 2)}
            </pre>
          </div>
        )}

        {canAct && (
          <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
            <Button variant="outline" onClick={() => setRejectOpen(true)} isLoading={reject.isPending}>
              <XCircle className="size-4" aria-hidden="true" />
              Reject
            </Button>
            <Button
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
        )}
      </CardContent>

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
    </Card>
  );
}
