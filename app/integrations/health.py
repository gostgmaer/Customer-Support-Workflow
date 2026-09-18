"""Lightweight "does this integration actually work" check, used by
`POST /api/v1/admin/integrations/{id}/test` so an admin finds out about a
bad API key/URL immediately instead of the first time an automatic hook
silently fails (see hooks.py's fail-open design)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import smtplib
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, short_response_body
from app.integrations.crypto import decrypt_secret
from app.integrations.docs_connector import get_docs_client
from app.integrations.mcp_client import list_tools as mcp_list_tools
from app.integrations.openapi_client import fetch_and_parse_spec
from app.integrations.stripe import StripeClient


async def test_connection(
    integration: Integration, *, session: AsyncSession | None = None
) -> tuple[bool, str]:
    try:
        if integration.type == "jira":
            async with build_http_client(integration) as client:
                response = await client.get("/rest/api/2/myself")
            if response.status_code == 200:
                return True, f"Authenticated as {response.json().get('displayName', 'unknown user')}"
            return False, f"JIRA returned {response.status_code}: {short_response_body(response.text)}"

        if integration.type == "woocommerce":
            async with build_http_client(integration) as client:
                response = await client.get("/wp-json/wc/v3/orders", params={"per_page": 1})
            if response.status_code == 200:
                return True, "Connected"
            return False, f"WooCommerce returned {response.status_code}: {short_response_body(response.text)}"

        if integration.type == "smtp":
            creds = json.loads(decrypt_secret(integration.encrypted_credentials))
            port = int(integration.config.get("smtp_port", 587))
            use_tls = bool(integration.config.get("use_tls", True))

            def _check() -> None:
                with smtplib.SMTP(integration.base_url, port, timeout=10) as smtp:
                    if use_tls:
                        smtp.starttls()
                    if creds.get("username"):
                        smtp.login(creds["username"], creds.get("password", ""))

            await asyncio.to_thread(_check)
            return True, "Connected"

        if integration.type == "mcp":
            try:
                tools = await mcp_list_tools(integration)
            except IntegrationError as exc:
                return False, str(exc)
            # Mirrors the openapi branch below exactly (spec: Phase
            # 10.2) - persists the freshly-discovered tools into
            # config.discovered_tools so the admin UI can show a
            # "discovered tools" panel that survives a page reload
            # instead of only a one-time toast, with no signature/route
            # change needed: the caller (app.api.routes.integrations.test_integration)
            # already commits this mutation on success, generically,
            # exactly as it already does for openapi's spec_cache.
            integration.config = {
                **integration.config,
                "discovered_tools": [{"name": t.name, "description": t.description} for t in tools],
                "discovered_tools_cached_at": datetime.now(UTC).isoformat(),
            }
            if not tools:
                return True, "Connected - server exposes no tools"
            names = ", ".join(t.name for t in tools[:5])
            more = f" (+{len(tools) - 5} more)" if len(tools) > 5 else ""
            return True, f"Connected - {len(tools)} tool(s) available: {names}{more}"

        if integration.type == "openapi":
            try:
                operations = await fetch_and_parse_spec(integration)
            except IntegrationError as exc:
                return False, str(exc)
            # Discovery itself stays live here (unlike MCP's
            # config.discovered_tools above, nothing else in this
            # codebase reads config.spec_cache as ground truth between
            # Tests either - app.integrations.openapi_client.list_operations
            # reads this cache for actual tool-selection calls, which is
            # the real reason it's persisted, not just UI display). The
            # caller (app.api.routes.integrations.test_integration)
            # commits this mutation on success.
            integration.config = {
                **integration.config,
                "spec_cache": [dataclasses.asdict(op) for op in operations],
                "spec_cached_at": datetime.now(UTC).isoformat(),
            }
            if not operations:
                return True, "Connected - spec has no operations"
            names = ", ".join(op.operation_id for op in operations[:5])
            more = f" (+{len(operations) - 5} more)" if len(operations) > 5 else ""
            return True, f"Connected - {len(operations)} operation(s) available: {names}{more}"

        if integration.type == "docs":
            # Heavier than the other branches here (this fetches every
            # page's full content, not just a list) - ConfluenceClient/
            # NotionClient only expose fetch_documents(), not a cheaper
            # "list titles only" call, an accepted MVP simplification
            # (see app.integrations.docs_connector's module docstring).
            try:
                documents = await get_docs_client(integration, session=session).fetch_documents()
            except IntegrationError as exc:
                return False, str(exc)
            if not documents:
                return True, "Connected - no documents found"
            titles = ", ".join(d.title for d in documents[:5])
            more = f" (+{len(documents) - 5} more)" if len(documents) > 5 else ""
            return True, f"Connected - {len(documents)} document(s) available: {titles}{more}"

        if integration.type == "stripe":
            try:
                balance = await StripeClient(integration).get_balance()
            except IntegrationError as exc:
                return False, str(exc)
            available = balance.get("available", [])
            if available:
                amount = available[0].get("amount", 0) / 100
                currency = available[0].get("currency", "").upper()
                return True, f"Connected - available balance {amount:.2f} {currency}"
            return True, "Connected"

        # custom: any non-5xx response counts as "reachable" - we don't know
        # this API's shape, so we can't assert more than that.
        async with build_http_client(integration) as client:
            response = await client.get("/")
        if response.status_code < 500:
            return True, f"Reachable (HTTP {response.status_code})"
        return False, f"Server error (HTTP {response.status_code})"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
