from collections.abc import AsyncIterator

import pytest_asyncio

from app.database import SQLiteRepository


@pytest_asyncio.fixture
async def repository(tmp_path) -> AsyncIterator[SQLiteRepository]:
    repository = SQLiteRepository(f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}")
    await repository.init()
    try:
        yield repository
    finally:
        await repository.dispose()

