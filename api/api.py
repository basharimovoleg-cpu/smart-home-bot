"""
FastAPI роутер: валидация initData, свет, задачи (CRUD), история, рецепты, webhook Telegram.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import subprocess
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from config import settings
from database import (
    add_movie_download,
    add_user,
    complete_task_with_history,
    create_recipe,
    create_recipe_category,
    create_task,
    delete_movie_download,
    delete_recipe,
    delete_recipe_category,
    delete_task,
    get_all_tasks,
    get_all_users,
    get_movie_downloads,
    get_recipe,
    get_recipe_categories,
    get_recipes,
    get_setting,
    get_task_history,
    return_task_from_history,
    set_setting,
    update_download_state,
    update_recipe,
    update_task,
)
from tuya_client import TuyaError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FIELD_LENGTHS = {
    "title": 200,
    "ingredients": 5000,
    "steps": 10000,
    "category_name": 100,
    "task_title": 200,
}


def validate_image_upload(image: UploadFile) -> None:
    if not image or not image.filename:
        return
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format. Allowed: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}",
        )
    if image.size and image.size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")


# ── Модели ──────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    task_date: str  # YYYY-MM-DD


class TaskUpdate(BaseModel):
    title: str | None = None
    task_date: str | None = None  # YYYY-MM-DD


# ── Валидация initData Telegram ─────────────────────────────────

async def get_current_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
) -> dict[str, Any]:
    """Криптографическая проверка initData от Telegram Web App.

    Алгоритм: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    parsed_qs = parse_qs(x_telegram_init_data)
    parsed: dict[str, str] = {k: v[0] for k, v in parsed_qs.items()}

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash in initData")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if computed_hash != received_hash:
        raise HTTPException(status_code=401, detail="Invalid initData hash")

    user_str = parsed.get("user", "{}")
    try:
        user: dict[str, Any] = json.loads(user_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Invalid user data in initData")

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user id in initData")

    await add_user(user_id)

    allowed = settings.allowed_user_ids
    if allowed and user_id not in allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    return {"user_id": user_id, "user": user}


# ── Модели ──────────────────────────────────────────────────────

class LightToggleRequest(BaseModel):
    mode: str  # "all", "main", "rims"


# ── Настройки (Settings) ──────────────────────────────────────────

class SettingUpdate(BaseModel):
    key: str
    value: str


@router.get("/settings")
async def list_settings(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Получить все настройки (без чувствительных значений)."""
    from database import get_all_settings
    all_settings = await get_all_settings()

    # Маскируем пароли
    masked = {}
    for k, v in all_settings.items():
        if "pass" in k.lower() or "secret" in k.lower() or "token" in k.lower():
            masked[k] = "***" + v[-4:] if len(v) > 4 else "***"
        else:
            masked[k] = v
    return masked


@router.post("/settings")
async def save_setting(
    body: SettingUpdate,
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Сохранить настройку в БД и обновить os.environ."""
    import os

    key = body.key.strip()
    value = body.value.strip()

    if not key:
        raise HTTPException(status_code=400, detail="Key is required")

    await set_setting(key, value)
    os.environ[key.upper()] = value

    return {"success": True, "key": key, "saved": True}


# ── Webhook Telegram ──────────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Приём апдейтов от Telegram через webhook."""
    wb_logger = logging.getLogger("webhook")

    bot = request.app.state.bot
    dp = request.app.state.dp

    if bot is None or dp is None:
        wb_logger.error("Webhook: bot or dispatcher not initialized")
        raise HTTPException(status_code=503, detail="Bot not initialized")

    try:
        body = await request.json()
        from aiogram.types import Update
        update = Update.model_validate(body)
        await dp.feed_webhook_update(bot, update)
    except Exception as e:
        wb_logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing error")

    return {"ok": True}


# ── Свет ────────────────────────────────────────────────────────

@router.get("/light/schema")
async def light_schema(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Возвращает спецификацию устройства: все DP-коды и их значения."""
    manager = request.app.state.device_manager
    if manager is None:
        raise HTTPException(status_code=503, detail="Device manager not initialized")

    try:
        raw = await asyncio.to_thread(manager.get_raw_status)
        return {"success": True, "result": raw}
    except TuyaError as e:
        raise HTTPException(status_code=502, detail=f"Tuya API error: {e}")
    except Exception:
        raise HTTPException(status_code=502, detail="Internal server error")


@router.post("/light/toggle")
async def toggle_light(
    body: LightToggleRequest,
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Управление светом: mode = all / main / rims."""
    manager = request.app.state.device_manager
    if manager is None:
        raise HTTPException(status_code=503, detail="Device manager not initialized")

    mode = body.mode

    if mode not in ("all", "main", "rims"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}. Use all, main, or rims.")

    try:
        await asyncio.to_thread(manager.refresh)

        if mode == "all":
            new_state = await asyncio.to_thread(manager.toggle_all)
            result = {"all_on": new_state}
        elif mode == "main":
            new_state = await asyncio.to_thread(manager.toggle_main_light)
            result = {"main_light": new_state}
        else:
            new_state = await asyncio.to_thread(manager.toggle_obodki)
            result = {"obodki": new_state}

        return {
            "success": True,
            "mode": mode,
            "obodki": manager.state.obodki,
            "main_light": manager.state.main_light,
            "all_on": manager.state.all_on(),
            **result,
        }
    except HTTPException:
        raise
    except TuyaError as e:
        raise HTTPException(status_code=502, detail=f"Tuya API error: {e}")
    except Exception:
        raise HTTPException(status_code=502, detail="Internal server error")


@router.get("/light/status")
async def light_status(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Получить текущее состояние света."""
    manager = request.app.state.device_manager
    if manager is None:
        raise HTTPException(status_code=503, detail="Device manager not initialized")

    try:
        await asyncio.to_thread(manager.refresh)
        return {
            "obodki": manager.state.obodki,
            "main_light": manager.state.main_light,
            "all_on": manager.state.all_on(),
        }
    except TuyaError as e:
        raise HTTPException(status_code=502, detail=f"Tuya API error: {e}")
    except Exception:
        raise HTTPException(status_code=502, detail="Internal server error")


# ── Усыпление ПК ─────────────────────────────────────────────────

@router.post("/pc/sleep")
async def pc_sleep(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Отправить Windows-ПК в спящий режим (локально, без SSH)."""
    import platform

    if platform.system() != "Windows":
        raise HTTPException(
            status_code=503,
            detail="PC sleep доступен только при локальном запуске на Windows",
        )

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=502,
                detail=f"Команда сна вернула код {result.returncode}: {result.stderr}",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Таймаут выполнения команды сна")
    except Exception as e:
        logger.error(f"Sleep command failed: {e}")
        raise HTTPException(status_code=502, detail=f"Не удалось усыпить ПК: {e}")

    return {"success": True, "message": "ПК уходит в сон 💤"}


@router.post("/pc/wake")
async def pc_wake(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Разбудить ПК через Wake-on-LAN (Magic Packet).
    Работает только если ПК в той же локальной сети (broadcast 255.255.255.255).
    Из облака не сработает — вернёт предупреждение."""
    mac = settings.pc_mac
    if not mac:
        raise HTTPException(status_code=400, detail="PC_MAC не задан в .env")

    # Парсим MAC-адрес (формат XX-XX-XX-XX-XX-XX или XX:XX:XX:XX:XX:XX)
    mac_clean = mac.replace("-", ":").replace(" ", "")
    parts = mac_clean.split(":")
    if len(parts) != 6:
        raise HTTPException(status_code=400, detail=f"Неверный формат MAC: {mac}")

    mac_bytes = bytes(int(p, 16) for p in parts)
    magic_packet = b"\xff" * 6 + mac_bytes * 16

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.sendto(magic_packet, ("255.255.255.255", 9))
    finally:
        sock.close()

    return {"success": True, "message": "Magic packet отправлен — ПК просыпается ⚡"}


# ── Кино: поиск и загрузка ─────────────────────────────────────

class MovieDownloadRequest(BaseModel):
    torrent_id: str
    title: str
    quality: str = ""
    size_text: str = ""
    category: str = "movies"


QUALITY_RANGE = {
    "4K": (50, 99),
    "1080p": (40, 49),
    "720p": (20, 39),
}


@router.get("/movies/search")
async def search_movies(
    q: str = Query(..., min_length=2),
    quality: str = Query("1080p"),
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Поиск фильмов на rutracker."""
    from rutracker import rutracker as rt
    import os

    has_creds = (
        settings.rutracker_user or os.getenv("RUTRACKER_USER", "")
    ) and (
        settings.rutracker_pass or os.getenv("RUTRACKER_PASS", "")
    )
    if not has_creds:
        raise HTTPException(
            status_code=503,
            detail="Поиск не настроен. Открой Mini App → ⚙️ Настройки и введи rutracker_user и rutracker_pass.",
        )

    min_q, max_q = QUALITY_RANGE.get(quality, (40, 99))
    results = await asyncio.to_thread(rt.search, q, min_q, max_q)

    return {
        "results": [
            {
                "torrent_id": r.torrent_id,
                "title": r.title,
                "size_text": r.size_text,
                "seeds": r.seeds,
                "quality": r.quality,
                "category": r.category,
                "rank": r.rank,
                "year": r.year,
            }
            for r in results
        ]
    }


@router.post("/movies/download")
async def add_movie_download_req(
    body: MovieDownloadRequest,
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Скачать .torrent с rutracker и отправить в qBittorrent."""
    from rutracker import rutracker as rt
    from qb_client import qb as _qb

    # Скачиваем .torrent файл через нашу сессию (с куками rutracker)
    torrent_data = await asyncio.to_thread(rt.download_torrent, body.torrent_id)
    if not torrent_data:
        raise HTTPException(status_code=502, detail="Не удалось скачать торрент-файл с rutracker")

    # Сохраняем во временный файл и отправляем в qBittorrent
    save_path = "D:\\Фильмы" if body.category == "movies" else "D:\\Сериалы"
    fd, tmp_path = tempfile.mkstemp(suffix=".torrent")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        f.write(torrent_data)

    try:
        qb_result = await _qb.add_torrent_file(tmp_path, save_path, body.category)
    finally:
        os.unlink(tmp_path)

    if not qb_result.get("success"):
        raise HTTPException(status_code=502, detail=f"qBittorrent: {qb_result.get('error', 'unknown')}")

    # Найти hash только что добавленного торрента — самый новый
    qb_torrents = await _qb.get_torrents()
    qb_hash = ""
    if qb_torrents:
        newest = max(qb_torrents, key=lambda t: t.get("added_on", 0))
        qb_hash = newest.get("hash", "")

    dl_id = await add_movie_download(
        title=body.title,
        torrent_id=body.torrent_id,
        magnet="",
        category=body.category,
        quality=body.quality,
        size_text=body.size_text,
    )

    if qb_hash:
        await update_download_state(dl_id, "downloading", 0.0, qb_hash)

    return {
        "success": True,
        "download_id": dl_id,
        "message": f"Загрузка «{body.title}» начата",
    }


@router.get("/movies/downloads")
async def list_movie_downloads(
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Список всех загрузок с прогрессом из qBittorrent."""
    from qb_client import qb as _qb

    qb_torrents = await _qb.get_torrents()
    db_downloads = await get_movie_downloads()

    qb_by_hash = {t["hash"]: t for t in qb_torrents}
    items = []

    for dl in db_downloads:
        info = {
            "id": dl["id"],
            "title": dl["title"],
            "category": dl["category"],
            "quality": dl["quality"],
            "size_text": dl["size_text"],
            "state": dl["state"],
            "progress": dl["progress"],
        }

        # Ищем прогресс из qBittorrent
        for qbt in qb_torrents:
            qb_name = qbt["name"].lower()
            dl_title = dl["title"].lower()
            if dl.get("qb_hash") and qbt["hash"] == dl["qb_hash"]:
                match = True
            elif dl_title[:15] in qb_name or qb_name[:15] in dl_title:
                match = True
            else:
                dl_words = set(dl_title.split()[:5])
                qb_words = set(qb_name.split()[:10])
                match = len(dl_words & qb_words) >= 2

            if match:
                info["progress"] = qbt["progress"]
                qb_state = qbt["state"]
                if qb_state in ("uploading", "pausedUP", "queuedUP", "checkingUP", "forcedUP"):
                    info["state"] = "completed"
                elif qb_state in ("pausedDL",):
                    info["state"] = "pausedDL"
                else:
                    info["state"] = "downloading"

                if qbt["hash"] and not dl.get("qb_hash"):
                    await update_download_state(dl["id"], info["state"], qbt["progress"], qbt["hash"])
                break
        
        # Fallback: если hash не найден, ищем самый новый торрент с таким же прогрессом > 0
        if not dl.get("qb_hash"):
            for qbt in sorted(qb_torrents, key=lambda t: t.get("added_on", 0), reverse=True):
                if qbt["progress"] > 0:
                    info["progress"] = qbt["progress"]
                    info["state"] = "downloading"
                    await update_download_state(dl["id"], "downloading", qbt["progress"], qbt["hash"])
                    break

        items.append(info)

    return {"downloads": items}


@router.delete("/movies/downloads/{download_id}")
async def remove_movie_download(
    download_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Удалить запись о загрузке из истории."""
    ok = await delete_movie_download(download_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Download not found")
    return {"success": True}


@router.get("/movies/quality-preference")
async def get_quality_pref(
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Текущее предпочтение качества (хранится в БД)."""
    # Пока храним в глобальной переменной, потом — в таблице настроек
    return {"preference": getattr(settings, "movie_quality", "1080p")}


# ── Задачи ──────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """Список всех невыполненных задач (общий)."""
    tasks = await get_all_tasks()
    return {"tasks": tasks}


@router.post("/tasks")
async def add_task(
    body: TaskCreate,
    request: Request,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, object]:
    """Создать новую задачу (общую)."""
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if len(body.title.strip()) > MAX_FIELD_LENGTHS["task_title"]:
        raise HTTPException(status_code=400, detail=f"Title too long (max {MAX_FIELD_LENGTHS['task_title']} chars)")
    if not body.task_date:
        raise HTTPException(status_code=400, detail="Date is required")

    task_id: int = await create_task(body.title.strip(), body.task_date)

    # Оповестить всех пользователей
    bot = request.app.state.bot
    if bot is not None:
        user_data = auth.get("user", {})
        creator = user_data.get("first_name", "Кто-то")
        users = await get_all_users()
        for uid in users:
            try:
                await bot.send_message(
                    uid,
                    f"📋 {creator} создал(а) задачу:\n\n«{body.title.strip()}»\n📅 {body.task_date}",
                )
            except Exception:
                pass

    return {"id": task_id, "title": body.title.strip(), "task_date": body.task_date}


@router.put("/tasks/{task_id}")
async def edit_task(
    task_id: int,
    body: TaskUpdate,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Обновить заголовок и/или дату задачи."""
    if body.title is not None and not body.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if body.task_date is not None and not body.task_date.strip():
        raise HTTPException(status_code=400, detail="Date cannot be empty")

    updated = await update_task(
        task_id,
        title=body.title,
        task_date=body.task_date,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found or already completed")
    return {"success": True}


@router.post("/tasks/{task_id}/complete")
async def mark_complete(
    task_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Пометить задачу как выполненную — перенос в историю с именем исполнителя."""
    user_data: dict[str, Any] = auth.get("user", {})
    completed_by = user_data.get("first_name", "Неизвестный")

    updated: bool = await complete_task_with_history(task_id, completed_by)
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found or already completed")
    return {"success": True, "completed_by": completed_by}


@router.delete("/tasks/{task_id}")
async def remove_task(
    task_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, bool]:
    """Удалить задачу."""
    removed: bool = await delete_task(task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True}


# ── История ─────────────────────────────────────────────────────

@router.get("/tasks/history")
async def list_history(
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """История выполненных задач, сгруппированная по датам."""
    history = await get_task_history()
    return {"history": history}


@router.post("/tasks/history/{history_id}/return")
async def return_task(
    history_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Вернуть задачу из истории обратно в активные."""
    ok: bool = await return_task_from_history(history_id)
    if not ok:
        raise HTTPException(status_code=404, detail="History entry not found")
    return {"success": True}


# ── Рецепты: категории ────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str


@router.get("/categories")
async def list_categories(
    auth: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Список всех категорий рецептов."""
    return await get_recipe_categories()


@router.post("/categories")
async def add_category(
    body: CategoryCreate,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Создать новую категорию."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    cat_id = await create_recipe_category(name)
    return {"id": cat_id, "name": name}


@router.delete("/categories/{category_id}")
async def remove_category(
    category_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Удалить категорию. Рецепты не удаляются — им выставляется category_id = NULL."""
    deleted = await delete_recipe_category(category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"success": True}


# ── Рецепты ────────────────────────────────────────────────────────

@router.get("/recipes")
async def list_recipes(
    category_id: int | None = Query(None),
    auth: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Список рецептов. ?category_id=X для фильтрации."""
    return await get_recipes(category_id)


@router.post("/recipes")
async def add_recipe(
    title: str = Form(...),
    category_id: int = Form(...),
    ingredients: str = Form(...),
    steps: str = Form(...),
    image: UploadFile | None = File(None),
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Создать рецепт с загрузкой фото (multipart/form-data)."""
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if len(title) > MAX_FIELD_LENGTHS["title"]:
        raise HTTPException(status_code=400, detail=f"Title too long (max {MAX_FIELD_LENGTHS['title']} chars)")
    if len(ingredients) > MAX_FIELD_LENGTHS["ingredients"]:
        raise HTTPException(status_code=400, detail=f"Ingredients too long (max {MAX_FIELD_LENGTHS['ingredients']} chars)")
    if len(steps) > MAX_FIELD_LENGTHS["steps"]:
        raise HTTPException(status_code=400, detail=f"Steps too long (max {MAX_FIELD_LENGTHS['steps']} chars)")

    validate_image_upload(image)

    image_url = ""
    if image and image.filename:
        # Генерируем уникальное имя
        ext = Path(image.filename).suffix or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = Path("static/images/recipes") / filename
        content = await image.read()
        save_path.write_bytes(content)
        image_url = f"/static/images/recipes/{filename}"

    recipe_id = await create_recipe(
        title=title.strip(),
        category_id=category_id,
        ingredients=ingredients,
        steps=steps,
        image_url=image_url,
    )
    return {
        "id": recipe_id,
        "title": title.strip(),
        "category_id": category_id,
        "image_url": image_url,
    }


@router.put("/recipes/{recipe_id}")
async def edit_recipe(
    recipe_id: int,
    title: str = Form(...),
    category_id: int = Form(...),
    ingredients: str = Form(...),
    steps: str = Form(...),
    image: UploadFile | None = File(None),
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Обновить рецепт. Если передан новый файл — заменить картинку."""
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if len(title) > MAX_FIELD_LENGTHS["title"]:
        raise HTTPException(status_code=400, detail=f"Title too long (max {MAX_FIELD_LENGTHS['title']} chars)")
    if len(ingredients) > MAX_FIELD_LENGTHS["ingredients"]:
        raise HTTPException(status_code=400, detail=f"Ingredients too long (max {MAX_FIELD_LENGTHS['ingredients']} chars)")
    if len(steps) > MAX_FIELD_LENGTHS["steps"]:
        raise HTTPException(status_code=400, detail=f"Steps too long (max {MAX_FIELD_LENGTHS['steps']} chars)")

    validate_image_upload(image)

    # Получаем старые данные
    old = await get_recipe(recipe_id)
    image_url = None

    if image and image.filename:
        # Удаляем старую картинку
        if old and old.get("image_url"):
            old_path = Path(str(old["image_url"]).lstrip("/"))
            if old_path.exists():
                old_path.unlink()

        # Сохраняем новую
        ext = Path(image.filename).suffix or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = Path("static/images/recipes") / filename
        content = await image.read()
        save_path.write_bytes(content)
        image_url = f"/static/images/recipes/{filename}"

    await update_recipe(
        recipe_id=recipe_id,
        title=title.strip(),
        category_id=category_id,
        ingredients=ingredients,
        steps=steps,
        image_url=image_url,
    )
    return {"success": True, "id": recipe_id}


@router.delete("/recipes/{recipe_id}")
async def remove_recipe(
    recipe_id: int,
    auth: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Удалить рецепт и его картинку с диска."""
    data = await delete_recipe(recipe_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Удаляем файл картинки
    image_url = data.get("image_url", "")
    if image_url:
        img_path = Path(str(image_url).lstrip("/"))
        if img_path.exists():
            img_path.unlink()

    return {"success": True}
