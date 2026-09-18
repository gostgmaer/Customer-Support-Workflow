"""app.integrations.woocommerce.WooCommerceClient - HTTP calls mocked with
respx (no real WooCommerce store)."""

import pytest
import respx
from httpx import Response

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.woocommerce import WooCommerceClient


def _woo_integration() -> Integration:
    return Integration(
        id="int_woo_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test Store",
        type="woocommerce",
        base_url="https://shop.example.com",
        auth_type="basic",
        encrypted_credentials=encode_credentials({"username": "ck_abc", "password": "cs_xyz"}),
        config={},
        enabled=True,
        created_by="staff_1",
    )


@pytest.mark.asyncio
@respx.mock
async def test_find_order_returns_first_match():
    respx.get("https://shop.example.com/wp-json/wc/v3/orders").mock(
        return_value=Response(
            200, json=[{"id": 1001, "number": "1001", "status": "processing", "total": "89.99"}]
        )
    )
    client = WooCommerceClient(_woo_integration())

    order = await client.find_order("1001")

    assert order["id"] == 1001
    assert order["status"] == "processing"


@pytest.mark.asyncio
@respx.mock
async def test_find_order_returns_none_when_no_match():
    respx.get("https://shop.example.com/wp-json/wc/v3/orders").mock(return_value=Response(200, json=[]))
    client = WooCommerceClient(_woo_integration())

    assert await client.find_order("nonexistent") is None


@pytest.mark.asyncio
@respx.mock
async def test_find_order_raises_on_error_response():
    respx.get("https://shop.example.com/wp-json/wc/v3/orders").mock(
        return_value=Response(401, text="unauthorized")
    )
    client = WooCommerceClient(_woo_integration())

    with pytest.raises(IntegrationError):
        await client.find_order("1001")
