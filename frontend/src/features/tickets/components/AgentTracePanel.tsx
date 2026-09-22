"use client";

import { format } from "date-fns";
import { ChevronDown, ListTree, Wrench } from "lucide-react";
import { useState } from "react";

import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";

import { useTicketTrace } from "../hooks";
import type { ToolExecutionEntry, WorkflowEventEntry } from "@/types/api";

function EventRow({ event }: { event: WorkflowEventEntry }) {
  const [open, setOpen] = useState(false);
  const hasData = Object.keys(event.data).length > 0;
  const statusVariant = event.status === "succeeded" ? "success" : event.status === "failed" ? "danger" : "warning";

  return (
    <li className="border-b border-border py-2 last:border-b-0">
      <button
        type="button"
        onClick={() => hasData && setOpen((v) => !v)}
        disabled={!hasData}
        className="flex w-full items-center justify-between gap-3 text-left disabled:cursor-default"
      >
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-mono text-xs text-foreground">{event.node_name}</span>
          <Badge variant={statusVariant}>{event.status}</Badge>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          {event.duration_ms !== null && <span>{Math.round(event.duration_ms)}ms</span>}
          {hasData && (
            <ChevronDown
              className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          )}
        </div>
      </button>
      {open && hasData && (
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap wrap-break-word rounded-md bg-secondary/60 p-2 text-xs text-foreground">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      )}
    </li>
  );
}

function ToolExecutionRow({ execution }: { execution: ToolExecutionEntry }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="border-b border-border py-2 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-2">
          <Wrench className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="truncate font-mono text-xs text-foreground">{execution.tool_name}</span>
          <Badge variant={execution.success ? "success" : "danger"}>
            {execution.success ? "success" : "failed"}
          </Badge>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          {execution.duration_ms !== null && <span>{Math.round(execution.duration_ms)}ms</span>}
          <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </div>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Arguments</p>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap wrap-break-word rounded-md bg-secondary/60 p-2 text-xs text-foreground">
              {JSON.stringify(execution.arguments, null, 2)}
            </pre>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Result</p>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap wrap-break-word rounded-md bg-secondary/60 p-2 text-xs text-foreground">
              {JSON.stringify(execution.result_summary, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </li>
  );
}

export function AgentTracePanel({ ticketId, hasWorkflowRun }: { ticketId: string; hasWorkflowRun: boolean }) {
  const trace = useTicketTrace(ticketId, hasWorkflowRun);

  if (!hasWorkflowRun) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <ListTree className="size-4 text-muted-foreground" aria-hidden="true" />
          Agent activity trace
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {trace.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-3/4" />
          </div>
        )}

        {trace.isError && <ApiErrorState error={trace.error} />}

        {trace.data && (
          <>
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Workflow steps ({trace.data.events.length})
              </p>
              {trace.data.events.length === 0 ? (
                <p className="text-sm text-muted-foreground">No steps recorded yet.</p>
              ) : (
                <ul>
                  {trace.data.events.map((event, i) => (
                    <EventRow key={`${event.node_name}-${i}`} event={event} />
                  ))}
                </ul>
              )}
            </div>

            {trace.data.tool_executions.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Tool calls ({trace.data.tool_executions.length})
                </p>
                <ul>
                  {trace.data.tool_executions.map((execution, i) => (
                    <ToolExecutionRow key={`${execution.tool_name}-${i}`} execution={execution} />
                  ))}
                </ul>
              </div>
            )}

            {trace.data.events.length > 0 && (
              <p className="text-xs text-muted-foreground">
                First step {format(new Date(trace.data.events[0].created_at), "MMM d, h:mm:ss a")}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
