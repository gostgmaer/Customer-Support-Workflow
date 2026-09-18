from __future__ import annotations

from sqlalchemy import func, select

from app.domain.models import ModelRequest
from app.repositories.base import TenantScopedRepository


class ModelRequestRepository(TenantScopedRepository):
    async def record(
        self,
        *,
        workflow_run_id: str | None,
        node_name: str,
        purpose: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        success: bool = True,
    ) -> ModelRequest:
        entry = ModelRequest(
            tenant_id=self.tenant_id,
            workflow_run_id=workflow_run_id,
            node_name=node_name,
            purpose=purpose,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            success=success,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def total_cost_for_run(self, workflow_run_id: str) -> float:
        stmt = self._scope(
            select(func.coalesce(func.sum(ModelRequest.estimated_cost_usd), 0.0)).where(
                ModelRequest.workflow_run_id == workflow_run_id
            ),
            ModelRequest,
        )
        result = await self.session.execute(stmt)
        return float(result.scalar_one())
