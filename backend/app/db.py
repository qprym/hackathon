from datetime import UTC, datetime
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings().database_url, pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30}
    if settings().database_url.startswith("sqlite") else {},
)
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def sqlite_options(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(engine, expire_on_commit=False)


def initialize_development_schema():
    """Keep unversioned local SQLite databases compatible without discarding data."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Production schema changes must use Alembic")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {column['name'] for column in inspect(connection).get_columns('runs')}
        if 'access_scope' not in columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN access_scope JSON NOT NULL DEFAULT '[]'"))
        columns = {column['name'] for column in inspect(connection).get_columns('documents')}
        if 'ingestion_meta' not in columns:
            connection.execute(text("ALTER TABLE documents ADD COLUMN ingestion_meta JSON NOT NULL DEFAULT '{}'"))


def get_db():
    with SessionLocal() as db:
        yield db
