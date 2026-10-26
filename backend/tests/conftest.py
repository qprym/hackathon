import os
from pathlib import Path
import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).resolve().parent / "test.db")
os.environ["INLINE_WORKER"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["AUTO_FETCH_RSS"] = "false"
os.environ["LLM_API_KEY"] = "test-key-never-use-provider"
os.environ["LLM_REQUEST_LIMIT"] = "20"
os.environ["LLM_TEST_LIMIT_RUB"] = "0"
os.environ["NEURAL_RANKING_WORKER"] = "false"

from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine, SessionLocal


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    # Gateway tests explicitly replace this function with their own transport fake.
    import app.llm as llm
    def forbidden(*args, **kwargs):
        raise AssertionError('Tests must not call a paid LLM provider')
    monkeypatch.setattr(llm.httpx, 'post', forbidden)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app, headers={"X-Alfa-Request": "1"}) as client:
        response = client.post("/api/auth/login", json={"username": "demo", "password": "demo-alfa-2026"})
        assert response.status_code == 200
        yield client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
