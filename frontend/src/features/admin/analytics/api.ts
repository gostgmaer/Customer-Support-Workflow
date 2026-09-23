import { apiFetch } from "@/lib/api/client";
import type { AnalyticsSummary } from "@/types/api";

export function getAnalyticsSummary(days = 30) {
  return apiFetch<AnalyticsSummary>("/api/v1/analytics/summary", { query: { days } });
}
