import pytest
from django.db.utils import OperationalError
from rest_framework.test import APIClient


def test_healthz_ok(db):
    client = APIClient()
    response = client.get("/healthz/")
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert data["service"] == "construction-erp"


def test_healthz_db_fail(monkeypatch):
    client = APIClient()

    class _FailCursor:
        def __enter__(self):
            raise OperationalError("db down")

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FailConnection:
        def cursor(self):
            return _FailCursor()

    from django.db import connections

    monkeypatch.setattr(connections["default"], "cursor", lambda: _FailCursor())

    response = client.get("/healthz/")
    data = response.json()
    assert response.status_code == 503
    assert data["status"] == "fail"
    assert data["db"] == "fail"
