from sqlalchemy import select

from app.db.models import RunAPICall


class UsageService:
    def __init__(self, repository): self.repository = repository
    async def for_run(self, run_id: str) -> dict:
        async with self.repository.session() as s:
            rows = (await s.execute(select(RunAPICall).where(RunAPICall.run_id == run_id))).scalars().all()
        return self._summary(rows, run_id)
    async def total(self) -> dict:
        async with self.repository.session() as s: rows = (await s.execute(select(RunAPICall))).scalars().all()
        return self._summary(rows, None)
    @staticmethod
    def _summary(rows, run_id):
        return {"run_id": run_id, "calls": len(rows), "llm_calls": sum(r.api_type == "llm" for r in rows), "search_calls": sum(r.api_type == "search" for r in rows), "input_tokens": sum(r.input_tokens or 0 for r in rows), "output_tokens": sum(r.output_tokens or 0 for r in rows), "total_tokens": sum(r.total_tokens or 0 for r in rows), "cost_usd": round(sum(float(r.cost_usd or 0) for r in rows), 6), "latency_ms": sum(r.latency_ms or 0 for r in rows)}
