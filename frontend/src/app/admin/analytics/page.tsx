"use client";

import { AlertTriangle, CheckCircle2, Clock, Star, TicketIcon, TrendingUp } from "lucide-react";

import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { ApiErrorState } from "@/components/ui/ApiErrorState";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { BarList } from "@/features/admin/analytics/components/BarList";
import { StatTile } from "@/features/admin/analytics/components/StatTile";
import { useAnalyticsSummary } from "@/features/admin/analytics/hooks";

function formatMinutes(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function formatPercent(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${Math.round(ratio * 100)}%`;
}

function AnalyticsContent() {
  const summary = useAnalyticsSummary(30);

  if (summary.isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (summary.isError || !summary.data) {
    return <ApiErrorState error={summary.error} />;
  }

  const data = summary.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Last 30 days, from {new Date(data.period_start).toLocaleDateString()} to{" "}
          {new Date(data.period_end).toLocaleDateString()}. Every number here is a real aggregation over
          stored tickets/workflow runs/feedback - nothing is estimated.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Total tickets" value={String(data.total_tickets)} icon={TicketIcon} />
        <StatTile label="Resolved" value={String(data.resolved_tickets)} icon={CheckCircle2} tone="success" />
        <StatTile label="Open" value={String(data.open_tickets)} icon={Clock} />
        <StatTile
          label="SLA breached"
          value={`${data.sla_breached_count} (${formatPercent(data.sla_breach_rate)})`}
          icon={AlertTriangle}
          tone={data.sla_breached_count > 0 ? "danger" : "default"}
        />
        <StatTile label="Avg resolution" value={formatMinutes(data.avg_resolution_minutes)} icon={Clock} />
        <StatTile
          label="Median resolution"
          value={formatMinutes(data.median_resolution_minutes)}
          icon={Clock}
        />
        <StatTile
          label="Escalation rate"
          value={`${formatPercent(data.escalation_rate)} (${data.escalated_workflow_runs}/${data.total_workflow_runs})`}
          icon={TrendingUp}
        />
        <StatTile
          label="CSAT average"
          value={data.csat_average !== null ? `${data.csat_average.toFixed(1)} / 5 (${data.csat_count})` : "No ratings yet"}
          icon={Star}
          tone={data.csat_average !== null && data.csat_average < 3 ? "danger" : "success"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <BarList
          title="Tickets by intent"
          items={data.tickets_by_intent.map((row) => ({ label: row.intent, count: row.count }))}
        />
        <BarList
          title="Tickets by priority"
          items={data.tickets_by_priority.map((row) => ({ label: row.priority, count: row.count }))}
        />
      </div>

      <BarList
        title="Ticket volume by day"
        items={data.ticket_volume_by_day.map((row) => ({ label: row.date, count: row.count }))}
      />

      <Card>
        <CardHeader>
          <CardTitle>Agent activity</CardTitle>
        </CardHeader>
        <CardContent>
          {data.agent_activity.length === 0 ? (
            <p className="text-sm text-muted-foreground">No staff decisions in this window.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-1.5">Staff</th>
                  <th className="py-1.5">Approved</th>
                  <th className="py-1.5">Rejected</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.agent_activity.map((row) => (
                  <tr key={row.staff_id}>
                    <td className="py-1.5">{row.staff_id}</td>
                    <td className="py-1.5">{row.approved_count}</td>
                    <td className="py-1.5">{row.rejected_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminAnalyticsPage() {
  return (
    <AuthGuard scope="staff" roles={["ADMIN"]}>
      <AppShell>
        <AnalyticsContent />
      </AppShell>
    </AuthGuard>
  );
}
