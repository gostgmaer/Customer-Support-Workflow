"""Admin CRUD for external-system connections (app.api.routes.integrations):
ADMIN-only, credentials are never echoed back, and a bad/missing
integration produces a clear error rather than a silent no-op.
"""

import pytest
import respx
from httpx import Response


@pytest.mark.asyncio
async def test_only_admin_can_manage_integrations(client, staff_token, admin_staff_token):
    headers = {"Authorization": f"Bearer {staff_token}"}
    body = {
        "name": "Prod JIRA",
        "type": "jira",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "token"},
        "config": {"project_key": "SUP"},
    }
    assert (await client.post("/api/v1/admin/integrations", json=body, headers=headers)).status_code == 403
    assert (await client.get("/api/v1/admin/integrations", headers=headers)).status_code == 403

    admin_headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post("/api/v1/admin/integrations", json=body, headers=admin_headers)
    assert create_response.status_code == 201


@pytest.mark.asyncio
async def test_credentials_are_never_returned(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Prod JIRA 2",
        "type": "jira",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "super-secret-token"},
        "config": {"project_key": "SUP"},
    }
    create_response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert create_response.status_code == 201
    created = create_response.json()
    assert "credentials" not in created
    assert "super-secret-token" not in str(created)
    assert "bot@example.com" not in str(created)
    assert sorted(created["credential_keys"]) == ["password", "username"]

    list_response = await client.get("/api/v1/admin/integrations", headers=headers)
    assert "super-secret-token" not in list_response.text


@pytest.mark.asyncio
async def test_duplicate_name_is_rejected(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Dupe Integration",
        "type": "custom",
        "base_url": "https://api.example.com",
        "auth_type": "bearer",
        "credentials": {"token": "abc"},
    }
    first = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_update_and_delete_integration(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Editable Integration",
        "type": "custom",
        "base_url": "https://api.example.com",
        "auth_type": "bearer",
        "credentials": {"token": "abc"},
    }
    created = (await client.post("/api/v1/admin/integrations", json=body, headers=headers)).json()

    update_response = await client.put(
        f"/api/v1/admin/integrations/{created['id']}", json={"enabled": False}, headers=headers
    )
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False

    delete_response = await client.delete(f"/api/v1/admin/integrations/{created['id']}", headers=headers)
    assert delete_response.status_code == 204

    list_response = await client.get("/api/v1/admin/integrations", headers=headers)
    assert created["id"] not in {i["id"] for i in list_response.json()}


@pytest.mark.asyncio
async def test_jira_integration_requires_a_project_key(client, admin_staff_token):
    body = {
        "name": "JIRA missing project key",
        "type": "jira",
        "base_url": "https://example.atlassian.net",
        "auth_type": "basic",
        "credentials": {"username": "bot@example.com", "password": "token"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mcp_integration_can_be_created(client, admin_staff_token):
    body = {
        "name": "Test MCP Server",
        "type": "mcp",
        "base_url": "https://mcp.example.com/mcp",
        "auth_type": "bearer",
        "credentials": {"token": "abc"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201
    assert response.json()["type"] == "mcp"


@pytest.mark.asyncio
async def test_mcp_integration_rejects_basic_auth(client, admin_staff_token):
    body = {
        "name": "Bad MCP Server",
        "type": "mcp",
        "base_url": "https://mcp.example.com/mcp",
        "auth_type": "basic",
        "credentials": {"username": "u", "password": "p"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mcp_integration_supports_no_auth(client, admin_staff_token):
    # Some genuinely public MCP servers (live-verified: mcp.deepwiki.com)
    # reject a request carrying any Authorization header at all, even an
    # unused one - auth_type="none" must be a real, distinct option, not
    # just "api_key with an empty value".
    body = {
        "name": "Public MCP Server",
        "type": "mcp",
        "base_url": "https://mcp.example.com/mcp",
        "auth_type": "none",
        "credentials": {},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201
    assert response.json()["auth_type"] == "none"


@pytest.mark.asyncio
async def test_openapi_integration_can_be_created_with_spec_url(client, admin_staff_token):
    body = {
        "name": "Test Storefront API",
        "type": "openapi",
        "base_url": "https://storefront.example.com/api",
        "auth_type": "bearer",
        "credentials": {"token": "abc"},
        "config": {"spec_url": "https://storefront.example.com/openapi.json"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201
    assert response.json()["type"] == "openapi"


@pytest.mark.asyncio
async def test_openapi_integration_can_be_created_with_spec_inline(client, admin_staff_token):
    body = {
        "name": "Inline Spec API",
        "type": "openapi",
        "base_url": "https://storefront.example.com/api",
        "auth_type": "api_key",
        "credentials": {"api_key": "abc"},
        "config": {"spec_inline": "openapi: '3.0.0'\npaths: {}\n"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_openapi_integration_requires_a_spec_source(client, admin_staff_token):
    body = {
        "name": "No Spec API",
        "type": "openapi",
        "base_url": "https://storefront.example.com/api",
        "auth_type": "bearer",
        "credentials": {"token": "abc"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_woocommerce_lookup_requires_a_configured_integration(client, staff_token):
    response = await client.post(
        "/api/v1/support/integrations/woocommerce/lookup",
        json={"order_number": "1001"},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_openapi_test_endpoint_fetches_and_caches_the_spec(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    respx.get("https://storefront.example.com/openapi.json").mock(
        return_value=Response(
            200,
            json={
                "openapi": "3.0.0",
                "paths": {"/orders/{orderId}": {"get": {"operationId": "getOrder", "parameters": []}}},
            },
        )
    )
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Test Endpoint Storefront",
            "type": "openapi",
            "base_url": "https://storefront.example.com/api",
            "auth_type": "bearer",
            "credentials": {"token": "abc"},
            "config": {"spec_url": "https://storefront.example.com/openapi.json"},
        },
        headers=headers,
    )
    integration_id = create_response.json()["id"]

    test_response = await client.post(f"/api/v1/admin/integrations/{integration_id}/test", headers=headers)

    assert test_response.status_code == 200
    body = test_response.json()
    assert body["ok"] is True
    assert "getOrder" in body["message"]

    # The spec_cache must actually persist - list_operations reads from it
    # rather than re-fetching live on every fallback-triggered message.
    list_response = await client.get("/api/v1/admin/integrations", headers=headers)
    integration = next(i for i in list_response.json() if i["id"] == integration_id)
    assert integration["config"]["spec_cache"][0]["operation_id"] == "getOrder"


@pytest.mark.asyncio
async def test_webhook_secret_is_masked_not_leaked_in_plaintext(client, admin_staff_token):
    """spec: Phase 10.1 - a real, previously-shipped bug: config.webhook_secret
    used to come back verbatim on every GET/POST/PUT, unlike credentials
    (masked via credential_keys)."""
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Webhook Secret Masking Test",
            "type": "stripe",
            "base_url": "https://api.stripe.com",
            "auth_type": "bearer",
            "credentials": {"token": "sk_test_abc"},
            "config": {"webhook_secret": "whsec_super_secret_value"},
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["config"]["webhook_secret"] is True
    assert "whsec_super_secret_value" not in str(created)

    integration_id = created["id"]
    get_response = await client.get("/api/v1/admin/integrations", headers=headers)
    assert "whsec_super_secret_value" not in get_response.text
    fetched = next(i for i in get_response.json() if i["id"] == integration_id)
    assert fetched["config"]["webhook_secret"] is True


@pytest.mark.asyncio
async def test_rotate_webhook_secret_returns_a_fresh_secret_once(client, admin_staff_token):
    """spec: Phase 10.1."""
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Rotate Secret Test",
            "type": "stripe",
            "base_url": "https://api.stripe.com",
            "auth_type": "bearer",
            "credentials": {"token": "sk_test_abc"},
            "config": {"webhook_secret": "whsec_original"},
        },
        headers=headers,
    )
    integration_id = create_response.json()["id"]

    rotate_response = await client.post(
        f"/api/v1/admin/integrations/{integration_id}/rotate-webhook-secret", headers=headers
    )
    assert rotate_response.status_code == 200, rotate_response.text
    new_secret = rotate_response.json()["webhook_secret"]
    assert new_secret != "whsec_original"
    assert len(new_secret) == 64  # secrets.token_hex(32)

    rotate_again_response = await client.post(
        f"/api/v1/admin/integrations/{integration_id}/rotate-webhook-secret", headers=headers
    )
    assert rotate_again_response.json()["webhook_secret"] != new_secret

    # The real value is only ever in the rotate response itself - a
    # subsequent GET must still show the masked boolean, not the secret.
    get_response = await client.get("/api/v1/admin/integrations", headers=headers)
    assert new_secret not in get_response.text
    fetched = next(i for i in get_response.json() if i["id"] == integration_id)
    assert fetched["config"]["webhook_secret"] is True


@pytest.mark.asyncio
async def test_rotate_webhook_secret_requires_admin(client, staff_token, admin_staff_token):
    admin_headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Rotate Secret RBAC Test",
            "type": "stripe",
            "base_url": "https://api.stripe.com",
            "auth_type": "bearer",
            "credentials": {"token": "sk_test_abc"},
            "config": {"webhook_secret": "whsec_original"},
        },
        headers=admin_headers,
    )
    integration_id = create_response.json()["id"]

    staff_headers = {"Authorization": f"Bearer {staff_token}"}
    response = await client.post(
        f"/api/v1/admin/integrations/{integration_id}/rotate-webhook-secret", headers=staff_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_rotate_webhook_secret_unknown_integration_fails(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    response = await client.post(
        "/api/v1/admin/integrations/does-not-exist/rotate-webhook-secret", headers=headers
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_drive_docs_integration_can_be_created(client, admin_staff_token):
    """spec: Phase 10.4."""
    body = {
        "name": "Test Google Drive",
        "type": "docs",
        "base_url": "https://www.googleapis.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "google_drive", "folder_id": "folder-123"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["auth_type"] == "oauth2"


@pytest.mark.asyncio
async def test_google_drive_docs_integration_requires_folder_id_or_file_ids(client, admin_staff_token):
    body = {
        "name": "No Source Google Drive",
        "type": "docs",
        "base_url": "https://www.googleapis.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "google_drive"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sharepoint_docs_integration_can_be_created(client, admin_staff_token):
    body = {
        "name": "Test SharePoint",
        "type": "docs",
        "base_url": "https://graph.microsoft.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "sharepoint", "drive_id": "drive-123"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_sharepoint_docs_integration_requires_drive_id(client, admin_staff_token):
    body = {
        "name": "No Drive Id SharePoint",
        "type": "docs",
        "base_url": "https://graph.microsoft.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "sharepoint"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_docs_integration_rejects_an_unknown_provider(client, admin_staff_token):
    body = {
        "name": "Unknown Provider Docs",
        "type": "docs",
        "base_url": "https://example.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "dropbox"},
    }
    response = await client.post(
        "/api/v1/admin/integrations", json=body, headers={"Authorization": f"Bearer {admin_staff_token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_oauth_authorize_redirects_to_the_providers_consent_screen(client, admin_staff_token):
    """spec: Phase 10.4 - staff-authenticated (unlike the callback route,
    which genuinely has no staff JWT - see test_oauth_callback_api.py)."""
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Authorize Test Google Drive",
            "type": "docs",
            "base_url": "https://www.googleapis.com",
            "auth_type": "oauth2",
            "credentials": {},
            "config": {"provider": "google_drive", "folder_id": "folder-123"},
        },
        headers=headers,
    )
    integration_id = create_response.json()["id"]

    response = await client.get(
        f"/api/v1/admin/integrations/{integration_id}/oauth/authorize", headers=headers
    )

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "state=" in location


@pytest.mark.asyncio
async def test_oauth_authorize_requires_admin(client, staff_token, admin_staff_token):
    admin_headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Authorize RBAC Test Google Drive",
            "type": "docs",
            "base_url": "https://www.googleapis.com",
            "auth_type": "oauth2",
            "credentials": {},
            "config": {"provider": "google_drive", "folder_id": "folder-123"},
        },
        headers=admin_headers,
    )
    integration_id = create_response.json()["id"]

    staff_headers = {"Authorization": f"Bearer {staff_token}"}
    response = await client.get(
        f"/api/v1/admin/integrations/{integration_id}/oauth/authorize", headers=staff_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_oauth_authorize_rejects_a_non_oauth2_integration(client, admin_staff_token):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    create_response = await client.post(
        "/api/v1/admin/integrations",
        json={
            "name": "Not An OAuth2 Integration",
            "type": "custom",
            "base_url": "https://api.example.com",
            "auth_type": "bearer",
            "credentials": {"token": "abc"},
        },
        headers=headers,
    )
    integration_id = create_response.json()["id"]

    response = await client.get(
        f"/api/v1/admin/integrations/{integration_id}/oauth/authorize", headers=headers
    )
    assert response.status_code == 400
