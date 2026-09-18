# User Guide

A practical, role-by-role guide to using the running application. For "how it
works under the hood," see `docs/ARCHITECTURE.md`; for the raw HTTP API, see
`docs/API.md`. This guide assumes the app is already running (`make dev` +
`make seed` for a local backend, `cd frontend && pnpm dev` for the web UI -
see the root `README.md` for first-time setup).

## What this system is

An AI customer support platform **for e-commerce**: a customer chats with
an AI agent that can look up their orders/payments/subscriptions, answer
questions from a knowledge base, and handle the real order lifecycle -
check status, cancel, request a refund (full or partial), process a
return, retry a failed payment, change a subscription plan - either
against this app's own order data or, once connected, a real external
storefront - always under policy guardrails, always with a human able to
step in. Anything the AI can't safely resolve on its own becomes a ticket
in a staff queue, where a human reviews and approves or rejects it. Admins
connect the app to real external systems for this - a storefront, Stripe
for payments, plus supporting infrastructure like JIRA, email, and
knowledge sources (Confluence/Notion/Drive/SharePoint) - without any
redeploy.

## Roles

| Role | What they can do |
|---|---|
| **Customer** | Chat with the AI, ask about their own orders/refunds/subscriptions. No login to the staff side. |
| **Support Agent** | View and approve/reject tickets in the general queue. |
| **Support Manager** | Same as Support Agent (today's permission matrix treats them the same for ticket approval). |
| **Admin** | Everything above, plus: manage integrations, rotate secrets, manage staff accounts, edit runtime settings. |
| **Security Agent** | The only role (besides Admin) that can see and approve `SECURITY`/`FRAUD`/`LEGAL`-intent tickets - these never show up in the general queue for other roles. |

`make seed` creates one account per role (see the seed script's printed
output for exact usernames/passwords) plus two demo customers, so you can
log in as each role immediately without registering anything.

## Customer: the chat experience

Open the web app (`http://localhost:3000` by default) and register or log
in as a customer. You land on `/chat`.

- **Starting a conversation**: the first message you send creates a
  conversation automatically - there's no separate "new chat" step unless
  you click **New conversation** to start a fresh thread.
- **What you can ask**: order status, shipping, cancel an order, request a
  refund (full or partial - e.g. "refund me $20 for order ORD-1001"),
  returns, payment failures/retries, subscription plan changes, password
  reset, general product/policy questions (answered from the knowledge
  base). Anything outside this - or anything the AI has low confidence
  about, or a security/fraud-sounding message - gets escalated to a human
  instead of guessed at.
- **Confirmation before anything real happens**: a mutating request (cancel,
  refund, subscription change) always asks you to confirm in plain language
  before it's actually submitted - a bare "yes" in reply is understood as
  confirming the thing you were just asked about, not a new request.
- **Waiting for approval**: some requests (refunds, anything from an
  external tool call, security-flagged messages) need a staff member to
  approve them before they complete. While waiting, the chat shows an
  "awaiting approval" state and the message box is disabled - you'll see
  the outcome appear in the conversation once a staff member decides, no
  need to keep refreshing (the page polls automatically, and if the AI is
  connected to a real external storefront, a live push can update the
  conversation the instant a related event comes in from that storefront -
  see "Real-time updates" below).
- **Real-time updates**: if a connected storefront integration reports an
  event (e.g. "order shipped") for an order tied to your open conversation,
  you'll see it reflected without manually refreshing, as long as you have
  that conversation open in your browser at the time.

## Staff: the ticket queue

Log in at `/staff/login` with a staff account. You land on `/tickets`.

- **The queue**: filterable by status (open/resolved/rejected/etc.), scoped
  to what your role is allowed to see - a `SUPPORT_AGENT` never sees
  `SECURITY`/`FRAUD`/`LEGAL` tickets; those are `SECURITY_AGENT`/`ADMIN`
  only.
- **Opening a ticket** (`/tickets/{id}`) shows: the customer's problem, the
  AI's summary, the tools it already used, actions already taken, relevant
  knowledge documents it drew on, and why it's escalated. Depending on the
  ticket:
  - A **refund** ticket has an Approve/Reject decision. Approving actually
    processes the refund (through a real Stripe integration if one's
    connected and the order has a payment on file; otherwise it's recorded
    internally). Rejecting leaves the refund request marked rejected.
  - An **external tool call** ticket (from a connected MCP server or an
    OpenAPI-described storefront) shows exactly what the AI proposed to
    call and with what arguments, in an editable panel - you can correct an
    argument before approving (e.g. fix an order id) and only the corrected
    call ever actually runs, re-validated against the tool's real schema
    before it's dispatched. After approval, the real result (or a real
    error, if the call failed) is shown on the ticket.
  - A **WooCommerce lookup** panel (shown on every ticket) lets you pull a
    real order's status by number directly, independent of anything the AI
    did - it only actually returns a result once a WooCommerce integration
    is connected.
  - A **webhook-originated** ticket (intent `WEBHOOK`) is purely
    informational - a real event a connected storefront pushed in, filed on
    whichever conversation it could be matched to.
- **Manual JIRA creation**: a **Create in JIRA** button shows on any ticket
  that isn't already linked to one (e.g. escalation didn't auto-file it, or
  auto-filing failed) - it only actually works once a JIRA integration is
  connected.

## Admin: the console

Log in as an `ADMIN` staff account. Three admin-only pages, all under
`/admin`:

### Integrations (`/admin/integrations`)

Connect the app to external systems - no env var, no redeploy, takes effect
immediately.

**Six types have a full create/edit form in this page today**: JIRA,
Email (SMTP), WooCommerce, Custom API, MCP Server, and OpenAPI/Swagger.
Every integration card (of any type) has three generic actions:
- **Test** - checks the connection actually works right now (and, for
  MCP, also shows the tools it discovered, staying visible on the card
  afterward rather than disappearing after one toast message).
- **Enable/Disable** - a disabled integration is skipped everywhere
  without deleting its configuration.
- **Delete** - removes the integration entirely.

| Type | What it's for | Auth |
|---|---|---|
| **JIRA** | Auto-creates an issue on escalation, comments on approve/reject | Basic (bot email + API token) |
| **Email (SMTP)** | Emails the customer on approve/reject | Basic |
| **WooCommerce** | Staff-triggered order lookup from a ticket | Basic (consumer key/secret) |
| **Custom API** | Any other REST API (not called automatically yet) | api_key / bearer / basic |
| **MCP Server** | Extra tools the AI can propose calling as a fallback | api_key / bearer / none |
| **OpenAPI / Swagger** | Same fallback role as MCP, or the *primary* path for order/refund/subscription questions if tagged as the storefront | api_key / bearer / basic |

**Making an OpenAPI/MCP integration the primary storefront**: check "Use as
the primary storefront..." when creating/editing an OpenAPI integration
(this checkbox is OpenAPI-only in the form today). From then on, order
status/cancel/refund/returns/payment-retry/subscription questions for that
tenant route through this real external system first, instead of this
app's own internal tables - the AI can run the whole order lifecycle
against your real storefront. Also checking "Auto-answer read-only
lookups..." lets a plain status check answer immediately with no approval
ticket; anything that changes something (cancel, refund, etc.) always still
needs staff approval regardless of that setting.

**Two more types exist and work fully, but have no create form in this
page yet - Docs (Confluence/Notion/Google Drive/SharePoint) and Stripe.**
Creating and managing these today means calling the API directly (see
`docs/API.md`'s "Integrations" section) - e.g.
`POST /api/v1/admin/integrations` with `type: "docs"` or `type: "stripe"`,
using your admin JWT as a bearer token. Once created this way, the
integration still shows up on this page (with a generic icon) and its
Test/Enable/Disable/Delete buttons work normally - only its *type-specific*
actions have no button here yet:
- **Sync** (`POST .../{id}/sync`, Docs only) - pulls the latest content in
  now; there's no automatic schedule or UI button, so re-sync via the API
  whenever the source changes.
- **Rotate webhook secret** (`POST .../{id}/rotate-webhook-secret`, any
  type with a webhook secret) - generates a fresh signing secret and
  returns it exactly once; the previous secret stops working immediately.
  No UI button yet either.
- **Google Drive / SharePoint's OAuth2 connect step**
  (`GET .../{id}/oauth/authorize`) requires an admin bearer token to call,
  so it can't simply be clicked as a plain link in a browser today - an
  admin/engineer calls it directly (e.g. with `curl`, following the
  redirect) to complete the real Google/Microsoft consent flow. This
  needs an OAuth app registered first (see `docs/DEPLOYMENT.md`).

None of this needs code changes to work - it's a real, current gap in the
admin *UI* only, not in what the backend supports. If you're doing this
regularly, it's a reasonable next frontend task.

### Settings (`/admin/settings`)

Runtime settings that take effect immediately, per tenant, with no
redeploy - e.g. toggling mock-LLM mode on/off, adjusting confidence
thresholds. An override you set here takes permanent precedence over the
underlying environment variable until you explicitly reset it.

### Staff (`/admin/staff`)

Create new staff accounts and assign them a role (`SUPPORT_AGENT`,
`SUPPORT_MANAGER`, `ADMIN`, `SECURITY_AGENT`). This is the only way to grant
staff access beyond the seed data's demo accounts.

## Common walkthroughs

**Connect JIRA so escalations file real issues**: Integrations -> add a
`JIRA` integration with your Cloud site URL, a bot account's email + API
token, and the target project key. From then on, any newly-escalated
ticket auto-creates a JIRA issue, and approving/rejecting comments on it.

**Turn on a real external storefront**: Integrations -> add an `OpenAPI`
integration pointing at your storefront's spec, check "primary storefront",
click Test to confirm it discovered operations, then have a conversation
that asks about an order - it should now be answered (or proposed for
approval, if mutating) against your real storefront instead of this app's
seeded demo data.

**Take real refunds through Stripe**: since Stripe has no create form in
the admin UI yet, call the API directly with your admin JWT:
`POST /api/v1/admin/integrations` with `type: "stripe"`, `auth_type:
"bearer"`, `credentials: {"token": "sk_..."}`, `config: {"webhook_secret":
"..."}`. Then in your Stripe dashboard, point a webhook at
`/api/v1/webhooks/stripe/{integration_id}` for `payment_intent.succeeded`,
`payment_intent.payment_failed`, and `refund.updated`. Approving a refund
ticket for an order with a real payment on file now issues a real Stripe
refund; the webhook is what marks it fully completed once Stripe confirms
it. The integration then shows up normally on the Integrations page for
Test/Enable/Disable.

**Bring in your real docs for AI answers**: same API-first pattern - create
a `type: "docs"` integration (Confluence with `config.space_key`, Notion
with `config.database_id`, Google Drive with `config.folder_id`, or
SharePoint with `config.drive_id`; Drive/SharePoint also need
`auth_type: "oauth2"` and an OAuth app registered - see
`docs/DEPLOYMENT.md`), then `POST .../{id}/test` and `POST .../{id}/sync`
(or use the corresponding buttons once the admin UI grows a form for this
type). The AI's answers to product/policy questions now draw on this
content alongside (or instead of) the seeded sample knowledge base.

## Troubleshooting

See `docs/TROUBLESHOOTING.md` for common developer-facing issues (empty RAG
results, stuck confirmation loops, 401/429s, flaky tests). For "why did the
AI escalate this" or "why didn't the AI use my storefront," check the
ticket's own summary/reasoning first - it's written to be genuinely
explanatory, not a generic message.
