/**
 * Shared types mirroring the backend's Pydantic response shapes.
 * See ../../../docs/API.md for the source of truth.
 */

export type ErrorCode =
  | "VALIDATION_ERROR"
  | "AUTHENTICATION_ERROR"
  | "AUTHORIZATION_ERROR"
  | "TOOL_ERROR"
  | "LLM_ERROR"
  | "RETRIEVAL_ERROR"
  | "POLICY_ERROR"
  | "TIMEOUT_ERROR"
  | "RATE_LIMIT_ERROR"
  | "UNKNOWN_ERROR";

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
  retryable: boolean;
  severity: "low" | "medium" | "high";
  details: Record<string, unknown>;
}

export type StaffRole = "SUPPORT_AGENT" | "SUPPORT_MANAGER" | "ADMIN" | "SECURITY_AGENT";

export interface CustomerAuthResponse {
  access_token: string;
  customer_id: string;
  full_name: string;
}

export interface CustomerMe {
  id: string;
  email: string;
  full_name: string;
  tier: string;
}

export interface StaffLoginResponse {
  access_token: string;
  role: StaffRole;
}

export interface StaffUser {
  id: string;
  username: string;
  role: StaffRole;
  is_active: boolean;
  created_at: string;
}

export type ConversationStatus = string;

export interface Conversation {
  id: string;
  customer_id: string;
  channel: string;
  status: ConversationStatus;
  intent: string | null;
  priority: string | null;
  created_at: string;
}

export interface Message {
  role: "customer" | "assistant" | string;
  content: string;
  created_at: string;
}

export type MessageStatus = "resolved" | "escalated" | "awaiting_approval";

export interface SupportMessageResponse {
  conversation_id: string;
  workflow_run_id: string;
  status: MessageStatus;
  response: string | null;
  requires_human: boolean;
  ticket_id: string | null;
}

export interface SupportTicket {
  id: string;
  conversation_id: string;
  customer_id: string;
  workflow_run_id: string | null;
  intent: string;
  priority: string;
  status: string;
  summary: string;
  customer_problem: string;
  actions_taken: string[];
  tools_used: string[];
  relevant_documents: string[];
  reason_for_escalation: string;
  recommended_next_action: string;
  approved_by: string | null;
  external_ref: string | null;
  external_url: string | null;
  // Phase 8.2 - present only for an external-tool-call ticket (null for
  // a refund ticket, which has no proposed call to show).
  pending_call: { integration_name: string; tool_name: string; arguments: Record<string, unknown> } | null;
  execution_result: Record<string, unknown> | null;
  created_at: string;
}

export type IntegrationType = "jira" | "woocommerce" | "smtp" | "custom" | "mcp" | "openapi";
export type IntegrationAuthType = "api_key" | "bearer" | "basic" | "none";

export interface Integration {
  id: string;
  name: string;
  type: IntegrationType;
  base_url: string;
  auth_type: IntegrationAuthType;
  credential_keys: string[];
  config: Record<string, unknown>;
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WooCommerceOrderSummary {
  id: number;
  number: string;
  status: string;
  total: string;
  currency: string;
  date_created: string;
}

export type SettingSource = "override" | "default";

export interface SystemSetting {
  key: string;
  value: unknown;
  source: SettingSource;
  updated_by: string | null;
  updated_at: string | null;
}

export interface KnowledgeCategorySummary {
  category: string;
  article_count: number;
}

export interface KnowledgeArticleSummary {
  id: string;
  title: string;
  category: string;
  summary: string;
  view_count: number;
  helpful_percent: number | null;
  updated_at: string;
}

export interface KnowledgeArticleDetail {
  id: string;
  title: string;
  category: string;
  source: string;
  version: string;
  raw_text: string;
  view_count: number;
  helpful_yes_count: number;
  helpful_no_count: number;
  helpful_percent: number | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeAskSource {
  id: string;
  title: string;
  category: string;
}

export interface KnowledgeAskResponse {
  answer: string;
  grounded: boolean;
  sources: KnowledgeAskSource[];
}
