/**
 * UI-only rendering hints mirroring app.config.dynamic_settings.OVERRIDABLE_SETTINGS
 * (see docs/SECURITY.md's "DB-backed runtime settings"). The backend is the
 * actual source of truth and re-validates every write - this only decides
 * which input control to render and gives a human-readable description.
 */
export type SettingFieldType = "boolean" | "enum" | "float" | "int" | "nullable-float";

export interface SettingMetadata {
  label: string;
  description: string;
  type: SettingFieldType;
  options?: string[];
  min?: number;
  max?: number;
}

export const SETTINGS_METADATA: Record<string, SettingMetadata> = {
  mock_llm: {
    label: "Mock LLM",
    description: "Use the deterministic mock provider instead of a real LLM call.",
    type: "boolean",
  },
  default_llm_provider: {
    label: "Default LLM provider",
    description: "Primary provider for every purpose unless overridden per-profile.",
    type: "enum",
    options: ["google", "xai", "anthropic"],
  },
  fallback_llm_provider: {
    label: "Fallback LLM provider",
    description: "Used automatically if the default provider fails.",
    type: "enum",
    options: ["google", "xai", "anthropic"],
  },
  confidence_intent: {
    label: "Intent confidence threshold",
    description: "Below this, a message is escalated to a human instead of auto-classified.",
    type: "float",
    min: 0,
    max: 1,
  },
  confidence_retrieval: {
    label: "Retrieval confidence threshold",
    description: "Minimum similarity score for a knowledge-base match to be used.",
    type: "float",
    min: 0,
    max: 1,
  },
  rate_limit_per_window: {
    label: "Rate limit (requests)",
    description: "Max requests per customer within the rate-limit window.",
    type: "int",
    min: 1,
  },
  rate_limit_window_seconds: {
    label: "Rate limit window (seconds)",
    description: "Length of the rate-limit window.",
    type: "int",
    min: 1,
  },
  llm_budget_usd_per_run: {
    label: "LLM budget per run (USD)",
    description: "Caps estimated LLM spend per workflow run. Leave empty for unlimited.",
    type: "nullable-float",
    min: 0,
  },
  escalation_max_failed_attempts: {
    label: "Max regeneration attempts",
    description: "How many times a response can be regenerated before forced escalation.",
    type: "int",
    min: 1,
  },
};
