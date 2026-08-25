from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _prepare_sqlite_path(url: str) -> None:
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url.endswith(":memory:"):
        return
    path = Path(url.removeprefix(prefix))
    path.parent.mkdir(parents=True, exist_ok=True)


def create_configured_engine(url: str) -> Engine:
    _prepare_sqlite_path(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    configured = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(configured, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return configured


def assert_postgres_migration_current(configured_engine: Engine) -> None:
    if configured_engine.dialect.name != "postgresql":
        return
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_config)
    expected_heads = set(script.get_heads())
    with configured_engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
    if not current_heads or current_heads != expected_heads:
        raise RuntimeError(
            "PostgreSQL schema is empty or not at the Alembic head; "
            "run `uv run alembic upgrade head`"
        )


settings = get_settings()
engine = create_configured_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
