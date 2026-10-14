import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.auth import hash_password
from app.models import User
from app.migrations import migrate
import app.main as main


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    maintenance = None
    schema = "test_" + uuid.uuid4().hex
    if url:
        assert url.startswith("postgresql"), "TEST_DATABASE_URL deve apontar para PostgreSQL de testes"
        maintenance = create_engine(url)
        with maintenance.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    migrate(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        db.add(User(username="admin", name="Admin", role="admin", password_hash=hash_password("test-password-123")))
        db.commit()

    def test_db():
        with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr(main, "migrate", lambda: migrate(engine))
    try:
        with TestClient(main.app) as test_client:
            test_client.db_factory = factory
            login = test_client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
            test_client.headers["Authorization"] = "Bearer " + login.json()["token"]
            yield test_client
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
        if maintenance:
            with maintenance.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            maintenance.dispose()
