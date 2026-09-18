import type { IntegrationAuthType, IntegrationType } from "@/types/api";

export interface DynamicField {
  key: string;
  label: string;
  type: "text" | "email" | "password" | "checkbox";
  required?: boolean;
  placeholder?: string;
}

export interface IntegrationTypeMeta {
  label: string;
  description: string;
  baseUrlPlaceholder: string;
  /** Fixed for every type except "custom"/"mcp", which let the admin choose. */
  fixedAuthType: IntegrationAuthType | null;
  credentialFields: DynamicField[];
  configFields: DynamicField[];
  /**
   * Restricts which auth types the picker offers when fixedAuthType is
   * null. Undefined means "all of them" (custom's REST API can be behind
   * anything). MCP's Streamable HTTP client only sends a header, so it
   * has no way to express HTTP basic auth - see
   * app.integrations.mcp_client._auth_headers on the backend.
   */
  allowedAuthTypes?: IntegrationAuthType[];
}

export const INTEGRATION_TYPE_META: Record<IntegrationType, IntegrationTypeMeta> = {
  jira: {
    label: "JIRA",
    description: "Auto-creates an issue when a ticket is escalated, and comments on approve/reject.",
    baseUrlPlaceholder: "https://yourteam.atlassian.net",
    fixedAuthType: "basic",
    credentialFields: [
      { key: "username", label: "Email", type: "email", required: true },
      { key: "password", label: "API token", type: "password", required: true },
    ],
    configFields: [
      { key: "project_key", label: "Project key", type: "text", required: true, placeholder: "SUP" },
      { key: "issue_type", label: "Issue type (default: Task)", type: "text", placeholder: "Task" },
    ],
  },
  woocommerce: {
    label: "WooCommerce",
    description: "Lets staff look up an order by number from a ticket.",
    baseUrlPlaceholder: "https://yourstore.com",
    fixedAuthType: "basic",
    credentialFields: [
      { key: "username", label: "Consumer key", type: "text", required: true },
      { key: "password", label: "Consumer secret", type: "password", required: true },
    ],
    configFields: [],
  },
  smtp: {
    label: "Email (SMTP)",
    description: "Notifies the customer by email when their ticket is approved or rejected.",
    baseUrlPlaceholder: "smtp.example.com",
    fixedAuthType: "basic",
    credentialFields: [
      { key: "username", label: "Username", type: "text", required: true },
      { key: "password", label: "Password", type: "password", required: true },
    ],
    configFields: [
      {
        key: "from_email",
        label: "From address",
        type: "email",
        required: true,
        placeholder: "support@example.com",
      },
      { key: "smtp_port", label: "Port (default: 587)", type: "text", placeholder: "587" },
    ],
  },
  custom: {
    label: "Custom API",
    description: "Any other REST API - stored the same way, for future use by staff or new tools.",
    baseUrlPlaceholder: "https://api.example.com",
    fixedAuthType: null,
    credentialFields: [],
    configFields: [],
  },
  mcp: {
    label: "MCP Server",
    description:
      "Connects an MCP (Model Context Protocol) server so the AI agent can propose calling its tools. " +
      "Every proposed call needs staff approval before it actually runs, the same as a refund.",
    baseUrlPlaceholder: "https://mcp.example.com/mcp",
    fixedAuthType: null,
    // "none" matters here specifically: some genuinely public MCP servers
    // (live-verified: mcp.deepwiki.com) reject a request carrying any
    // Authorization header at all, even an unused placeholder one - see
    // app.integrations.mcp_client._auth_headers on the backend.
    allowedAuthTypes: ["api_key", "bearer", "none"],
    credentialFields: [],
    configFields: [],
  },
  openapi: {
    label: "OpenAPI / Swagger",
    description:
      "Connects a REST API (e.g. an external storefront) described by an OpenAPI/Swagger spec. Once " +
      "connected and tested, the AI agent can propose calling its operations - every proposal needs " +
      "staff approval before it actually runs, the same as a refund.",
    baseUrlPlaceholder: "https://api.example.com",
    fixedAuthType: null,
    // No allowedAuthTypes restriction - unlike MCP, a plain outbound REST
    // call (app.integrations.base.build_http_client) supports basic auth
    // fine, so all four options are offered, same as "custom".
    credentialFields: [],
    // The backend also accepts config.spec_inline (a pasted spec) for
    // APIs whose spec isn't published at a stable URL - not exposed here
    // yet since DynamicField has no textarea variant; connect via the API
    // directly if spec_url doesn't fit.
    configFields: [
      {
        key: "spec_url",
        label: "OpenAPI spec URL",
        type: "text",
        required: true,
        placeholder: "https://api.example.com/openapi.json",
      },
      {
        // Backend: app.agents.resolution._get_storefront_integration reads
        // config.role == "storefront" to route commerce intents (order
        // status/cancel/refund/...) here instead of this app's own
        // internal orders/payments tables - see CreateIntegrationDialog's
        // checkbox handling for how this maps to the string "storefront".
        key: "role",
        label: "Use as the primary storefront for order/refund/subscription questions",
        type: "checkbox",
      },
      {
        // Backend: only ever consulted when `role` above is also set, and
        // only ever skips the approval ticket for a read-only (GET/HEAD)
        // operation - see app.agents.resolution.resolve_via_storefront.
        key: "auto_execute_reads",
        label: "Auto-answer read-only lookups without a staff approval ticket",
        type: "checkbox",
      },
    ],
  },
};

export const CUSTOM_AUTH_CREDENTIAL_FIELDS: Record<IntegrationAuthType, DynamicField[]> = {
  api_key: [{ key: "api_key", label: "API key", type: "password", required: true }],
  bearer: [{ key: "token", label: "Bearer token", type: "password", required: true }],
  basic: [
    { key: "username", label: "Username", type: "text", required: true },
    { key: "password", label: "Password", type: "password", required: true },
  ],
  none: [],
};
