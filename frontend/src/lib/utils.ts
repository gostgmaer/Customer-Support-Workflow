// Re-exports the app's existing cn() (src/lib/utils/cn.ts) rather than
// duplicating it - shadcn/ui-generated components import from "@/lib/utils"
// by convention, the rest of this app's own components import from
// "@/lib/utils/cn" directly. Both paths resolve to the same implementation.
export { cn } from "./utils/cn";
