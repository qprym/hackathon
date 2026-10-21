from datetime import UTC, datetime
from sqlalchemy import create_engine, event
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


def get_db():
    with SessionLocal() as db:
        yield db
