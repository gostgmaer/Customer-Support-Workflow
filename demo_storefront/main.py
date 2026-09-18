"""A tiny, committed demo storefront (spec: Phase 8.1).

A standalone FastAPI app - the first second `FastAPI()` app in this repo -
standing in for a real external e-commerce storefront so the main app's
storefront-primary commerce routing (app.agents.resolution.resolve_via_storefront)
has a stable, permanent target to call and be live-verified against,
replacing the throwaway/uncommitted fixture used for Phase A2. FastAPI
auto-generates a real OpenAPI 3.1 spec at /openapi.json - nothing here is
hand-written, matching how the Petstore/A2 fixture worked.

Not production code: no auth, no persistence (in-memory, resets on
restart), no real payment/fulfillment logic anywhere. See store.py for the
seed data.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from demo_storefront.store import NON_MUTABLE_STATUSES, ORDERS, PAYMENTS, SUBSCRIPTIONS

app = FastAPI(title="Demo Storefront", version="1.0.0")


def _get_order(order_id: str) -> dict[str, Any]:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get(
    "/orders/{order_id}", operation_id="getOrderStatus", summary="Get the current status of a customer order"
)
def get_order_status(order_id: str) -> dict[str, Any]:
    return _get_order(order_id)


@app.post("/orders/{order_id}/cancel", operation_id="cancelOrder", summary="Cancel a customer order")
def cancel_order(order_id: str) -> dict[str, Any]:
    order = _get_order(order_id)
    if order["status"] in NON_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"order is already {order['status']}, cannot cancel")
    order["status"] = "cancelled"
    return order


@app.post(
    "/orders/{order_id}/refund", operation_id="refundOrder", summary="Refund all or part of a customer order"
)
def refund_order(order_id: str, amount: float, reason: str = "") -> dict[str, Any]:
    order = _get_order(order_id)
    if amount > order["total"]:
        raise HTTPException(status_code=400, detail="refund amount exceeds order total")
    return {"order_id": order_id, "refunded_amount": amount, "reason": reason, "status": "refund_issued"}


@app.post(
    "/orders/{order_id}/exchange",
    operation_id="exchangeOrder",
    summary="Request an exchange for a different variant of a customer order",
)
def exchange_order(order_id: str, requested_variant: str, reason: str = "") -> dict[str, Any]:
    order = _get_order(order_id)
    if order["status"] in NON_MUTABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"order is already {order['status']}, cannot exchange")
    return {
        "exchange_id": f"EXC-{order_id}",
        "order_id": order_id,
        "requested_variant": requested_variant,
        "reason": reason,
        "status": "pending_fulfillment",
    }


@app.patch(
    "/orders/{order_id}/shipping-address",
    operation_id="updateShippingAddress",
    summary="Update the shipping address of a customer order that has not yet shipped",
)
def update_shipping_address(
    order_id: str, line1: str, city: str, postal_code: str, country: str
) -> dict[str, Any]:
    order = _get_order(order_id)
    if order["status"] in NON_MUTABLE_STATUSES or order["status"] == "shipped":
        status = order["status"]
        raise HTTPException(status_code=409, detail=f"order is already {status}, cannot change address")
    order["shipping_address"] = {"line1": line1, "city": city, "postal_code": postal_code, "country": country}
    return order


@app.get(
    "/subscriptions/{customer_ref}",
    operation_id="getSubscription",
    summary="Get a customer's current subscription plan",
)
def get_subscription(customer_ref: str) -> dict[str, Any]:
    sub = SUBSCRIPTIONS.get(customer_ref)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    return sub


@app.patch(
    "/subscriptions/{customer_ref}",
    operation_id="changeSubscriptionPlan",
    summary="Upgrade or downgrade a customer's subscription plan",
)
def change_subscription_plan(customer_ref: str, new_plan: str) -> dict[str, Any]:
    sub = SUBSCRIPTIONS.get(customer_ref)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub["plan"] = new_plan
    return sub


@app.post(
    "/payments/{payment_id}/retry",
    operation_id="retryPayment",
    summary="Retry a previously failed payment",
)
def retry_payment(payment_id: str) -> dict[str, Any]:
    payment = PAYMENTS.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    payment["status"] = "succeeded" if payment["retryable"] else "failed"
    return payment
