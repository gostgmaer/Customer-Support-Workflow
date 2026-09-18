"""Structured JSON logging (spec §22).

Every log line carries request_id/conversation_id/customer_id_hash/
workflow_run_id/node_name via contextvars so nothing has to be threaded
through call signatures manually. Never log raw customer_id, passwords,
tokens, or payment data - see app.security.pii for redaction helpers used
before anything customer-supplied reaches a log line.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from contextvars import ContextVar

import structlog

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_conversation_id: ContextVar[str | None] = ContextVar("conversation_id", default=None)
_customer_id_hash: ContextVar[str | None] = ContextVar("customer_id_hash", default=None)
_workflow_run_id: ContextVar[str | None] = ContextVar("workflow_run_id", default=None)
_node_name: ContextVar[str | None] = ContextVar("node_name", default=None)


def hash_customer_id(customer_id: str) -> str:
    """One-way hash so logs never contain raw customer identifiers."""
    return hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:16]


def bind_context(
    *,
    request_id: str | None = None,
    conversation_id: str | None = None,
    customer_id: str | None = None,
    workflow_run_id: str | None = None,
    node_name: str | None = None,
) -> None:
    if request_id is not None:
        _request_id.set(request_id)
    if conversation_id is not None:
        _conversation_id.set(conversation_id)
    if customer_id is not None:
        _customer_id_hash.set(hash_customer_id(customer_id))
    if workflow_run_id is not None:
        _workflow_run_id.set(workflow_run_id)
    if node_name is not None:
        _node_name.set(node_name)


def clear_context() -> None:
    for var in (_request_id, _conversation_id, _customer_id_hash, _workflow_run_id, _node_name):
        var.set(None)


def _add_context(logger, method_name, event_dict):  # noqa: ANN001
    event_dict.setdefault("request_id", _request_id.get())
    event_dict.setdefault("conversation_id", _conversation_id.get())
    event_dict.setdefault("customer_id_hash", _customer_id_hash.get())
    event_dict.setdefault("workflow_run_id", _workflow_run_id.get())
    event_dict.setdefault("node_name", _node_name.get())
    return {k: v for k, v in event_dict.items() if v is not None}


def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
