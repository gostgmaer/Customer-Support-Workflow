import { useQuery } from "@tanstack/react-query";

import { getAnalyticsSummary } from "./api";

export function useAnalyticsSummary(days = 30) {
  return useQuery({
    queryKey: ["admin-analytics-summary", days],
    queryFn: () => getAnalyticsSummary(days),
  });
}
