# Support Console (frontend)

The web UI for the [Customer Support Workflow](../README.md) backend: a
customer chat, a staff ticket queue, and an admin console — one Next.js
app, role-based routing after login. See `../docs/API.md` for the API
this talks to.

## Stack

Next.js (App Router) · TypeScript (strict) · Tailwind CSS v4 · TanStack
Query · Zustand · React Hook Form + Zod · lucide-react

## Quick start

```bash
pnpm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL, defaults to http://localhost:8000
pnpm dev                           # http://localhost:3000
```

Requires the backend running and reachable at `NEXT_PUBLIC_API_URL`, with
`CORS_ALLOWED_ORIGINS` on the backend including `http://localhost:3000`
(the zero-setup default — see `../docs/DEPLOYMENT.md`). Run `make seed`
in the backend first so there's something to log in with:

- **Customers**: `alice@example.com` / `bob@example.com`, password `dev-customer-password` — or register a new one at `/register`.
- **Staff**: `agent_jane` (SUPPORT_AGENT), `manager_mo` (SUPPORT_MANAGER), `security_sam` (SECURITY_AGENT), `admin_priya` (ADMIN) — all password `dev-agent-password`.

## Routes

| Route | Who | What |
| --- | --- | --- |
| `/`, `/login`, `/register` | Anyone | Landing page, customer sign in/sign up |
| `/staff/login` | Anyone | Staff sign in |
| `/chat` | Customer | The support conversation |
| `/tickets`, `/tickets/[id]` | Staff | Ticket queue (auto-scoped to the caller's role — see `docs/SECURITY.md`'s "RBAC") and detail/approve/reject/JIRA/WooCommerce |
| `/admin/staff` | ADMIN | Create and list staff accounts |
| `/admin/settings` | ADMIN | View/edit/reset the backend's DB-backed runtime settings |
| `/admin/integrations` | ADMIN | Connect JIRA, email (SMTP), WooCommerce, an MCP server, an OpenAPI/Swagger API, or any other REST API |

Route protection is client-side (`components/layout/AuthGuard.tsx`), not
`middleware.ts` — the JWT lives in `localStorage` (see the trade-off
documented in `store/auth-store.ts`), which Next's edge middleware can't
read. The guard is a UX convenience; the real authorization boundary is
the backend re-checking the token on every request.

## Architecture

Feature-first, layered `Component → Hook → Service → HTTP client`:

```
src/
  app/                 routes only - no business logic
  components/ui/       generic, reusable primitives (Button, Dialog, Card, ...)
  components/layout/   AppShell (nav), AuthGuard (route protection)
  features/
    auth/              customer + staff login/register
    chat/              conversation bootstrap, message thread
    tickets/           queue, detail, approve/reject, JIRA link, WooCommerce lookup
    admin/staff/       staff account management
    admin/settings/    DB-backed runtime settings
    admin/integrations/ JIRA/WooCommerce/SMTP/custom API/MCP/OpenAPI connections
  lib/api/client.ts    the one place that calls fetch() - typed ApiError
  store/               Zustand: auth session, chat's active-conversation-id, toasts
  providers/           TanStack Query provider
  types/api.ts         types mirroring the backend's response shapes
```

Each feature's `api.ts` is the only thing that imports `lib/api/client`;
each feature's `hooks.ts` is the only thing that imports TanStack Query
for that feature. Components render, hooks fetch, services call HTTP —
never skip a layer.

## Known gaps (matching the backend's own "known gaps" honesty pattern)

- **One active conversation per customer.** There is no "list my
  conversations" backend endpoint (see `docs/API.md`), so this app
  remembers one active conversation per customer (`features/chat/store.ts`)
  rather than offering a conversation history/switcher. "New conversation"
  starts a fresh thread; the old one is still on the server, just not
  reachable from this UI.
- **No live push for ticket updates.** The ticket queue and a pending
  conversation both poll (`refetchInterval`) rather than using a
  websocket/SSE - fine at this scale, but a real-time desk would want push
  instead.
- **WooCommerce lookup is staff-triggered, not autonomous.** The AI never
  calls WooCommerce on its own - a staff member types an order number into
  the ticket detail panel. See `docs/SECURITY.md`'s "External
  integrations" for why.
- **JWT in `localStorage`**, not an httpOnly cookie - see the comment in
  `store/auth-store.ts` for the trade-off and why (the backend has no
  cookie-session concept to begin with).

## Commands

```bash
pnpm dev      # dev server
pnpm build    # production build (also type-checks)
pnpm lint     # eslint
```
