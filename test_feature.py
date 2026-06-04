"""
Тесты API: валидация initData, CRUD задач, свет.
"""
import os

# ── Переопределяем переменные окружения ДО любых импортов ──
# .env может содержать реальные ключи; для тестов нужны предсказуемые значения.
os.environ["BOT_TOKEN"] = "test_bot_token"
os.environ["TUYA_ACCESS_ID"] = ""
os.environ["TUYA_DEVICE_ID"] = ""

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient


def _make_init_data(user_id: int = 999, bot_token: str = "test_bot_token") -> str:
    """Создать валидную строку initData для тестов."""
    user = json.dumps({"id": user_id, "first_name": "Test", "username": "tester"})
    pairs = {"auth_date": "1700000000", "query_id": "test_q", "user": user}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    sk = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(sk, dcs.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = h
    return urlencode(pairs)


@pytest.fixture(scope="module")
def client():
    """Фикстура: тестовый клиент FastAPI."""
    import asyncio
    from pathlib import Path

    # Удаляем старую тестовую БД для чистой среды
    db_path = Path(__file__).parent / "data" / "bot.db"
    if db_path.exists():
        db_path.unlink()

    from database import init_db

    asyncio.run(init_db())

    from main import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Фикстура: заголовки с валидным initData."""
    return {"X-Telegram-Init-Data": _make_init_data()}


# ═══════════════════════════════════════════════════════════════
# Тесты авторизации
# ═══════════════════════════════════════════════════════════════

class TestAuth:
    def test_no_header_returns_422(self, client: TestClient):
        resp = client.get("/api/tasks")
        assert resp.status_code == 422

    def test_bad_hash_returns_401(self, client: TestClient):
        resp = client.get(
            "/api/tasks",
            headers={"X-Telegram-Init-Data": "user=%7B%7D&hash=badhash"},
        )
        assert resp.status_code == 401

    def test_valid_auth_access(self, client: TestClient, auth_headers: dict):
        resp = client.get("/api/tasks", headers=auth_headers)
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Тесты задач (CRUD)
# ═══════════════════════════════════════════════════════════════

class TestTasks:
    def test_empty_tasks_list(self, client: TestClient, auth_headers: dict):
        resp = client.get("/api/tasks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"tasks": []}

    def test_create_task(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/api/tasks",
            json={"title": "Купить корм", "task_date": "2026-06-01"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Купить корм"
        assert data["task_date"] == "2026-06-01"
        assert "id" in data

    def test_list_after_create(self, client: TestClient, auth_headers: dict):
        # Создаём задачу
        resp = client.post(
            "/api/tasks",
            json={"title": "Новая задача", "task_date": "2026-07-01"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        resp = client.get("/api/tasks", headers=auth_headers)
        assert resp.status_code == 200
        tasks = resp.json()["tasks"]
        assert len(tasks) >= 1

    def test_complete_task(self, client: TestClient, auth_headers: dict):
        # Создаём → выполняем
        resp = client.post(
            "/api/tasks",
            json={"title": "На проверку", "task_date": "2026-08-01"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        task_id = resp.json()["id"]

        resp = client.post(f"/api/tasks/{task_id}/complete", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

    def test_complete_nonexistent_task(self, client: TestClient, auth_headers: dict):
        resp = client.post("/api/tasks/99999/complete", headers=auth_headers)
        assert resp.status_code == 404

    def test_create_task_empty_title(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/api/tasks",
            json={"title": "", "task_date": "2026-06-01"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_create_task_no_date(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/api/tasks",
            json={"title": "Test", "task_date": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_delete_task(self, client: TestClient, auth_headers: dict):
        # Создаём → удаляем
        resp = client.post(
            "/api/tasks",
            json={"title": "Удаляемая", "task_date": "2026-09-01"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        task_id = resp.json()["id"]

        resp = client.delete(f"/api/tasks/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

    def test_delete_nonexistent_task(self, client: TestClient, auth_headers: dict):
        resp = client.delete("/api/tasks/99999", headers=auth_headers)
        assert resp.status_code == 404
