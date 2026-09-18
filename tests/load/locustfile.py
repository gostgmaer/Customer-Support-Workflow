"""Load test scaffold (spec §36).

Run against a seeded instance, e.g.:

    locust -f tests/load/locustfile.py --host http://localhost:8000

Sweep --users/--spawn-rate to hit the 10/50/100/500 RPS targets from the
spec and record p50/p95/p99 latency + error rate from Locust's own report;
this file intentionally does not attempt to simulate 500 RPS by itself.
"""

from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, task

TOKEN = os.environ.get("LOAD_TEST_TOKEN", "")


class SupportUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.conversation_id = f"conv_{uuid.uuid4()}"
        self.headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    @task(3)
    def order_status(self) -> None:
        self._post_message("Where is my order?")

    @task(1)
    def refund(self) -> None:
        self._post_message("The product arrived damaged, I want a refund.")

    @task(2)
    def product_question(self) -> None:
        self._post_message("What is the file upload limit on the free tier?")

    def _post_message(self, message: str) -> None:
        self.client.post(
            "/api/v1/support/messages",
            json={
                "conversation_id": self.conversation_id,
                "message_id": f"msg_{uuid.uuid4()}",
                "message": message,
                "channel": "web",
            },
            headers=self.headers,
        )
