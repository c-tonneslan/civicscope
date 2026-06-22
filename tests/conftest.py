import pytest
import sqlite3
from app import db
from fastapi.testclient import TestClient
from app.main import app, get_db

@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    yield conn
    conn.close()

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test.db"

    conn = sqlite3.connect(test_db)
    db.init_db(conn)
    conn.close()

    def override_get_db():
        conn = sqlite3.connect(test_db)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
