import {
  BookOpen,
  CreditCard,
  Package,
  Plug,
  Rocket,
  Shield,
  UserCog,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** Best-effort icon per category, matched by keyword since categories are
 * free-text (app.domain.models.knowledge.KnowledgeDocument.category) rather
 * than a fixed enum - falls back to a generic book icon. */
const KEYWORD_ICONS: [RegExp, LucideIcon][] = [
  [/getting.?start|onboard|setup/i, Rocket],
  [/bill|payment|invoice|subscription|refund/i, CreditCard],
  [/security|compliance|privacy|fraud/i, Shield],
  [/account|access|profile/i, UserCog],
  [/integrat|api|webhook|technical/i, Plug],
  [/order|shipping|product/i, Package],
];

export function iconForCategory(category: string): LucideIcon {
  const match = KEYWORD_ICONS.find(([pattern]) => pattern.test(category));
  return match ? match[1] : BookOpen;
}
