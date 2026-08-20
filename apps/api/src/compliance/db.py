from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Protocol, TypeVar, cast

import asyncpg  # type: ignore[import-untyped]  # The package has no PEP 561 marker.

from compliance.config.settings import Settings, get_settings

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""

_ContextValue = TypeVar("_ContextValue", covariant=True)


class _AsyncContext(Protocol[_ContextValue]):
    async def __aenter__(self) -> _ContextValue: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class DatabaseRow(Protocol):
    def __getitem__(self, key: str) -> object: ...


class DatabaseConnection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None: ...

    async def fetch(self, query: str, *args: object) -> list[DatabaseRow]: ...

    async def fetchrow(self, query: str, *args: object) -> DatabaseRow | None: ...

    async def fetchval(self, query: str, *args: object) -> object: ...

    def transaction(self) -> _AsyncContext[None]: ...


class DatabasePool(Protocol):
    def acquire(self) -> _AsyncContext[DatabaseConnection]: ...

    async def close(self) -> None: ...


def _default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


def _migration_files(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"migration directory does not exist: {migrations_dir}")
    return sorted(migrations_dir.glob("*.sql"), key=lambda path: path.name)


async def create_pool(
    settings: Settings | None = None, *, server_settings: Mapping[str, str] | None = None
) -> DatabasePool:
    active_settings = settings or get_settings()
    pool = await asyncpg.create_pool(
        dsn=str(active_settings.database_url), server_settings=server_settings
    )
    return cast(DatabasePool, pool)


async def apply_migrations(pool: DatabasePool, migrations_dir: Path | None = None) -> list[str]:
    migration_files = _migration_files(migrations_dir or _default_migrations_dir())
    applied_now: list[str] = []
    async with pool.acquire() as connection:
        await connection.execute(_MIGRATION_TABLE_SQL)
        async with connection.transaction():
            await connection.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
            rows = await connection.fetch("SELECT name FROM schema_migrations")
            applied = {cast(str, row["name"]) for row in rows}
            for migration_file in migration_files:
                if migration_file.name in applied:
                    continue
                await connection.execute(migration_file.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)", migration_file.name
                )
                applied_now.append(migration_file.name)
    return applied_now
