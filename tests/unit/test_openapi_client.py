"""app.integrations.openapi_client - spec parsing verified against a small
fixture spec (mirroring shapes confirmed against the real, public Swagger
Petstore v3 spec during development - nested $ref resolution, path/query/
body parameter placement); HTTP calls (both fetching the spec and calling
a parsed operation) mocked with respx, matching this codebase's existing
REST-integration test pattern (test_jira_client.py/test_woocommerce_client.py)."""

from __future__ import annotations

import pytest
import respx
from httpx import Response
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.openapi_client import (
    OpenApiOperationSpec,
    call_operation,
    fetch_and_parse_spec,
    list_operations,
    parse_operations,
)

_FIXTURE_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/orders/{orderId}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Get an order",
                "parameters": [
                    {"name": "orderId", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
            }
        },
        "/orders/{orderId}/cancel": {
            "post": {
                "operationId": "cancelOrder",
                "summary": "Cancel an order",
                "parameters": [
                    {"name": "orderId", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CancelRequest"}}
                    }
                },
            }
        },
        "/orders": {
            "get": {
                # no operationId - must synthesize one from method+path
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["open", "cancelled"]},
                    },
                ],
            }
        },
    },
    "components": {
        "schemas": {
            "CancelRequest": {
                "type": "object",
                "required": ["reason"],
                "properties": {
                    "reason": {"type": "string"},
                    "customer": {"$ref": "#/components/schemas/Customer"},
                },
            },
            "Customer": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
            },
        }
    },
}


def test_parse_operations_extracts_path_and_query_params():
    ops = {op.operation_id: op for op in parse_operations(_FIXTURE_SPEC)}

    get_order = ops["getOrder"]
    assert get_order.method == "GET"
    assert get_order.path == "/orders/{orderId}"
    assert get_order.param_locations == {"orderId": "path"}
    assert get_order.input_schema["required"] == ["orderId"]


def test_parse_operations_synthesizes_operation_id_when_missing():
    ops = {op.operation_id: op for op in parse_operations(_FIXTURE_SPEC)}

    assert "get_orders" in ops
    assert ops["get_orders"].param_locations == {"status": "query"}


def test_parse_operations_resolves_nested_refs_in_request_body():
    ops = {op.operation_id: op for op in parse_operations(_FIXTURE_SPEC)}
    cancel = ops["cancelOrder"]

    assert cancel.param_locations == {"orderId": "path", "reason": "body_field", "customer": "body_field"}
    assert "reason" in cancel.input_schema["required"]
    # nested $ref (CancelRequest.customer -> Customer) must be inlined, not
    # left as a dangling $ref jsonschema.validate couldn't resolve alone.
    customer_schema = cancel.input_schema["properties"]["customer"]
    assert customer_schema["properties"]["name"]["type"] == "string"


def test_parsed_schema_is_directly_usable_by_jsonschema_validate():
    ops = {op.operation_id: op for op in parse_operations(_FIXTURE_SPEC)}
    cancel = ops["cancelOrder"]

    jsonschema_validate(instance={"orderId": "o1", "reason": "changed mind"}, schema=cancel.input_schema)
    with pytest.raises(JsonSchemaValidationError):
        # missing required "reason"
        jsonschema_validate(instance={"orderId": "o1"}, schema=cancel.input_schema)


def _openapi_integration(**config) -> Integration:
    return Integration(
        id="int_openapi_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test Storefront",
        type="openapi",
        base_url="https://shop.example.com/api",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "abc"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )


@respx.mock
async def test_fetch_and_parse_spec_from_url():
    respx.get("https://shop.example.com/openapi.json").mock(return_value=Response(200, json=_FIXTURE_SPEC))
    integration = _openapi_integration(spec_url="https://shop.example.com/openapi.json")

    ops = await fetch_and_parse_spec(integration)

    assert {op.operation_id for op in ops} == {"getOrder", "cancelOrder", "get_orders"}


async def test_fetch_and_parse_spec_from_inline_yaml():
    yaml_spec = """
openapi: "3.0.0"
paths:
  /ping:
    get:
      operationId: ping
"""
    integration = _openapi_integration(spec_inline=yaml_spec)

    ops = await fetch_and_parse_spec(integration)

    assert [op.operation_id for op in ops] == ["ping"]


async def test_fetch_and_parse_spec_raises_with_neither_source():
    integration = _openapi_integration()

    with pytest.raises(IntegrationError):
        await fetch_and_parse_spec(integration)


async def test_list_operations_uses_cache_when_present():
    cached = [
        {
            "operation_id": "cached_op",
            "method": "GET",
            "path": "/x",
            "summary": "",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "param_locations": {},
        }
    ]
    integration = _openapi_integration(spec_url="https://shop.example.com/openapi.json", spec_cache=cached)

    # No respx mock registered - if this tried to fetch live it would error.
    ops = await list_operations(integration)

    assert len(ops) == 1
    assert ops[0].operation_id == "cached_op"


@respx.mock
async def test_call_operation_places_path_query_and_body_params_correctly():
    route = respx.post("https://shop.example.com/api/orders/order_1001/cancel").mock(
        return_value=Response(200, json={"status": "cancelled"})
    )
    integration = _openapi_integration()
    op = OpenApiOperationSpec(
        operation_id="cancelOrder",
        method="POST",
        path="/orders/{orderId}/cancel",
        summary="",
        input_schema={},
        param_locations={"orderId": "path", "reason": "body_field", "notify": "query"},
    )

    result = await call_operation(
        integration, op, {"orderId": "order_1001", "reason": "changed mind", "notify": "true"}
    )

    assert result == {"result": {"status": "cancelled"}}
    assert route.called
    request = route.calls.last.request
    assert request.url.params["notify"] == "true"
    import json as _json

    assert _json.loads(request.content) == {"reason": "changed mind"}


@respx.mock
async def test_call_operation_raises_integration_error_on_non_2xx():
    respx.get("https://shop.example.com/api/orders/order_1001").mock(
        return_value=Response(404, text="not found")
    )
    integration = _openapi_integration()
    op = OpenApiOperationSpec(
        operation_id="getOrder",
        method="GET",
        path="/orders/{orderId}",
        summary="",
        input_schema={},
        param_locations={"orderId": "path"},
    )

    with pytest.raises(IntegrationError):
        await call_operation(integration, op, {"orderId": "order_1001"})


@respx.mock
async def test_call_operation_raises_integration_error_on_timeout():
    """spec: Phase 12 audit - a transport-level failure (timeout,
    connection refused) was previously only verified by code inspection
    of the broad `except Exception` in call_operation, never by a real
    test - a commerce action proposed against an unreachable/slow
    storefront must surface as the same IntegrationError a 4xx/5xx
    response does, not an unhandled exception reaching the workflow."""
    import httpx

    respx.post("https://shop.example.com/api/orders/order_1001/refund").mock(
        side_effect=httpx.ConnectTimeout("connection timed out")
    )
    integration = _openapi_integration()
    op = OpenApiOperationSpec(
        operation_id="refundOrder",
        method="POST",
        path="/orders/{orderId}/refund",
        summary="",
        input_schema={},
        param_locations={"orderId": "path"},
    )

    with pytest.raises(IntegrationError, match="refundOrder"):
        await call_operation(integration, op, {"orderId": "order_1001"})


@respx.mock
async def test_call_operation_raises_integration_error_on_connection_refused():
    import httpx

    respx.get("https://shop.example.com/api/orders/order_1001").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    integration = _openapi_integration()
    op = OpenApiOperationSpec(
        operation_id="getOrder",
        method="GET",
        path="/orders/{orderId}",
        summary="",
        input_schema={},
        param_locations={"orderId": "path"},
    )

    with pytest.raises(IntegrationError):
        await call_operation(integration, op, {"orderId": "order_1001"})
