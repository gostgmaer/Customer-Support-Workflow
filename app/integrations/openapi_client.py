"""Client for OpenAPI/Swagger-described REST APIs (spec: Phase 7 - external
commerce tools). Lets an admin connect an external storefront (or any other
REST API) by pointing at its OpenAPI spec; operations are parsed into the
same catalog shape `app.integrations.mcp_client.McpToolSpec` already
provides, so `app.agents.external_tools` can offer MCP and OpenAPI
operations to the LLM as one unified menu.

Verified against a real public spec (Swagger Petstore v3,
https://petstore3.swagger.io/api/v3/openapi.json) before writing this,
not guessed from the OpenAPI spec documentation alone - see its
`parameters`/`requestBody`/`components.schemas` shapes, including nested
`$ref`s (e.g. Pet.category -> Category), which `_resolve_schema` below
handles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import yaml

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, short_response_body

_SPEC_FETCH_TIMEOUT_SECONDS = 15.0
_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
_MAX_REF_DEPTH = 6


@dataclass
class OpenApiOperationSpec:
    operation_id: str
    method: str  # GET/POST/PUT/PATCH/DELETE
    path: str  # e.g. "/orders/{orderId}/cancel" - relative to integration.base_url
    summary: str
    input_schema: dict[str, Any]  # flat object schema, same shape as McpToolSpec.input_schema
    param_locations: dict[str, str]  # name -> "path" | "query" | "header" | "body_field"


def _resolve_ref(ref: str, components: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        # External or non-schema ref (e.g. #/components/responses/...) - not
        # worth chasing for an argument schema; degrade to an opaque object
        # rather than raising, since not every operation needs it resolved.
        return {"type": "object"}
    return components.get("schemas", {}).get(ref[len(prefix) :], {"type": "object"})


def _resolve_schema(schema: Any, components: dict[str, Any], *, _depth: int = 0) -> dict[str, Any]:
    """Inlines `$ref`s so the result is a standalone schema `jsonschema.validate`
    can check without needing a resolver context. Real specs can nest refs
    arbitrarily deep (and some are self-referential) - `_MAX_REF_DEPTH` caps
    that at a reasonable depth for typical commerce-API request bodies
    rather than risking infinite recursion; deeper structures degrade to
    `{"type": "object"}` (documented v1 limitation, mirroring how the docs
    connectors accept degraded rich-text formatting)."""
    if _depth > _MAX_REF_DEPTH or not isinstance(schema, dict):
        return {"type": "object"}
    if "$ref" in schema:
        return _resolve_schema(_resolve_ref(schema["$ref"], components), components, _depth=_depth + 1)
    resolved = dict(schema)
    if isinstance(resolved.get("properties"), dict):
        resolved["properties"] = {
            name: _resolve_schema(prop, components, _depth=_depth + 1)
            for name, prop in resolved["properties"].items()
        }
    if "items" in resolved:
        resolved["items"] = _resolve_schema(resolved["items"], components, _depth=_depth + 1)
    for combinator in ("allOf", "oneOf", "anyOf"):
        if isinstance(resolved.get(combinator), list):
            resolved[combinator] = [
                _resolve_schema(sub, components, _depth=_depth + 1) for sub in resolved[combinator]
            ]
    return resolved


def _operation_id_from_path(method: str, path: str) -> str:
    slug = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f"{method}_{slug}" if slug else method


def parse_operations(spec: dict[str, Any]) -> list[OpenApiOperationSpec]:
    """Walks `spec["paths"]`, building one `OpenApiOperationSpec` per
    method. Only `application/json` request bodies are supported (not
    xml/form-urlencoded) - the rest of this codebase works in JSON
    throughout, and every real commerce API's JSON variant is functionally
    equivalent for our purposes. Cookie parameters are skipped (rare for
    the kind of APIs this targets, and not meaningfully fillable by an
    LLM-selected argument anyway)."""
    components = spec.get("components", {})
    operations: list[OpenApiOperationSpec] = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            properties: dict[str, Any] = {}
            required: list[str] = []
            param_locations: dict[str, str] = {}

            for param in op.get("parameters") or []:
                name = param.get("name")
                location = param.get("in")
                if not name or location not in ("path", "query", "header"):
                    continue
                properties[name] = _resolve_schema(param.get("schema") or {"type": "string"}, components)
                if param.get("required"):
                    required.append(name)
                param_locations[name] = location

            request_body = op.get("requestBody") or {}
            body_schema = request_body.get("content", {}).get("application/json", {}).get("schema")
            if body_schema:
                resolved_body = _resolve_schema(body_schema, components)
                for name, prop_schema in (resolved_body.get("properties") or {}).items():
                    properties[name] = prop_schema
                    param_locations[name] = "body_field"
                for name in resolved_body.get("required") or []:
                    if name not in required:
                        required.append(name)

            operations.append(
                OpenApiOperationSpec(
                    operation_id=op.get("operationId") or _operation_id_from_path(method, path),
                    method=method.upper(),
                    path=path,
                    summary=op.get("summary") or op.get("description") or "",
                    input_schema={"type": "object", "properties": properties, "required": required},
                    param_locations=param_locations,
                )
            )
    return operations


async def fetch_and_parse_spec(integration: Integration) -> list[OpenApiOperationSpec]:
    """Fetches the spec fresh from `config.spec_url`, or parses
    `config.spec_inline` directly - `CreateIntegrationRequest` already
    requires at least one to be set. The spec fetch itself is
    unauthenticated even when the integration has credentials configured:
    OpenAPI/Swagger documents are conventionally served publicly even when
    the API they describe requires auth - if a real integration needs an
    authenticated spec fetch, that's a documented fast-follow, not
    something to guess a default for."""
    config = integration.config or {}
    try:
        if config.get("spec_inline"):
            raw = config["spec_inline"]
            spec = yaml.safe_load(raw) if isinstance(raw, str) else raw
        elif config.get("spec_url"):
            async with httpx.AsyncClient(timeout=_SPEC_FETCH_TIMEOUT_SECONDS) as client:
                response = await client.get(config["spec_url"])
                response.raise_for_status()
                spec = yaml.safe_load(response.text)
        else:
            raise IntegrationError(f"OpenAPI integration '{integration.name}' has no spec_url or spec_inline")
    except IntegrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(
            f"Could not fetch/parse OpenAPI spec for '{integration.name}': {exc}"
        ) from exc
    if not isinstance(spec, dict):
        raise IntegrationError(f"OpenAPI spec for '{integration.name}' did not parse to an object")
    return parse_operations(spec)


async def list_operations(integration: Integration) -> list[OpenApiOperationSpec]:
    """Reads the cached, already-parsed catalog from `config.spec_cache`
    (populated by the admin "Test" action) when present - unlike MCP's
    `list_tools` (a cheap live RPC over an already-open session), fetching
    and parsing a full OpenAPI document on every fallback-triggered
    customer message is needlessly slow and fragile. Falls back to a live
    fetch+parse if no cache exists yet (e.g. immediately after connecting,
    before the admin has clicked Test)."""
    cache = (integration.config or {}).get("spec_cache")
    if cache:
        return [OpenApiOperationSpec(**op) for op in cache]
    return await fetch_and_parse_spec(integration)


async def call_operation(
    integration: Integration, op: OpenApiOperationSpec, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Only ever called from app.workflow.nodes.human_approval, after a
    staff member has approved the proposed call - same never-before-
    approval contract as app.integrations.mcp_client.call_tool."""
    path = op.path
    query_params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    body: dict[str, Any] = {}
    for name, value in arguments.items():
        location = op.param_locations.get(name)
        if location == "path":
            path = path.replace(f"{{{name}}}", str(value))
        elif location == "query":
            query_params[name] = value
        elif location == "header":
            headers[name] = str(value)
        elif location == "body_field":
            body[name] = value

    try:
        async with build_http_client(integration) as client:
            response = await client.request(
                op.method, path, params=query_params or None, json=body or None, headers=headers or None
            )
    except IntegrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(f"OpenAPI operation '{op.operation_id}' failed: {exc}") from exc

    if response.status_code >= 400:
        raise IntegrationError(
            f"OpenAPI operation '{op.operation_id}' returned {response.status_code}: "
            f"{short_response_body(response.text)}"
        )
    try:
        return {"result": response.json()}
    except ValueError:
        return {"result": response.text}
