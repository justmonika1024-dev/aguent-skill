from __future__ import annotations

from typing import Any


class ArchiveService:
    """Persistence adapter hook; transactions are supplied by the DB agent."""

    def __init__(self, repository: Any = None) -> None:
        self.repository = repository

    async def archive(self, context: Any) -> Any:
        if self.repository is None:
            return context.run_id
        method = getattr(self.repository, "archive_run", None)
        if method is None:
            return context.run_id
        result = method(context)
        return await result if hasattr(result, "__await__") else result

