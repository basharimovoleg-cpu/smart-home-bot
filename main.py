"""
Точка входа: FastAPI + aiogram (Webhook через Cloudflare-туннель).
"""
import asyncio
import logging
import os
import re
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

# ── Default credentials (cloud fallback) ──────────────────────
# Эти значения используются только если соответствующие переменные
# не заданы через .env или переменные окружения Render.
_DEFAULTS = {
    "RUTRACKER_USER": "oleg.basharimov",
    "RUTRACKER_PASS": "7414522Oleg",
}
for _k, _v in _DEFAULTS.items():
    if not os.getenv(_k):
        os.environ[_k] = _v

import asyncssh

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings

sys.stdout.reconfigure(encoding="utf-8")

BANNER = r"""
╔══════════════════════════════════════════════╗
║        🏠  УМНЫЙ ДОМ — БОТ ЗАПУЩЕН  🏠      ║
║                                              ║
║   Telegram: @deaepseek_home_bot              ║
║   Режим:   {mode}              ║
║                                              ║
║   Команды бота:                              ║
║     /start  — главное меню                   ║
║     /help   — справка                        ║
║     /status — состояние света                ║
╚══════════════════════════════════════════════╝
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _setup_menu_button(bot) -> None:
    """Установка кнопки меню Telegram (Mini App)."""
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    webapp_url = settings.webapp_url

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Умный Дом",
                web_app=WebAppInfo(url=webapp_url),
            )
        )
        logger.info(f"Menu button set: {webapp_url}")
    except Exception as e:
        logger.warning(f"Failed to set menu button: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл: БД, бот, планировщик, webhook."""
    # ── Инициализация БД ──
    from database import init_db, get_all_settings
    await init_db()
    logger.info("Database initialized")

    # ── Загрузка настроек из БД в окружение (приоритет: env var > DB) ──
    db_settings = await get_all_settings()
    for key, value in db_settings.items():
        env_key = key.upper()
        if not os.getenv(env_key):
            os.environ[env_key] = value
    if db_settings:
        logger.info(f"Loaded {len(db_settings)} settings from DB")

    # ── Создание директорий для статики ──
    img_dir = Path("static/images/recipes")
    img_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Images directory ensured: {img_dir}")

    # ── Инициализация qBittorrent ──
    try:
        from qb_client import qb as _qb
        logged_in = await _qb.login()
        if logged_in:
            logger.info("qBittorrent connected")
        else:
            logger.warning("qBittorrent login failed — movie downloads disabled")
    except Exception as e:
        logger.warning(f"qBittorrent unavailable: {e}")

    # ── Создание бота ──
    from bot.bot import create_bot, dp
    import bot.bot as bot_module

    bot = None
    device_manager = None
    try:
        bot = create_bot()
        bot_module.bot = bot
        device_manager = getattr(bot, "device_manager", None)
        if device_manager is not None:
            logger.info("DeviceManager initialized successfully")
        else:
            logger.warning("No Tuya credentials — light control disabled")
    except Exception as e:
        logger.error(f"Bot creation failed: {e}")
        logger.warning("Bot will not be available")

    app.state.device_manager = device_manager
    app.state.bot = bot
    app.state.dp = dp

    # ── Запуск планировщика ──
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from bot.scheduler import setup_scheduler

    scheduler = AsyncIOScheduler()
    if bot is not None:
        setup_scheduler(scheduler, bot)
    scheduler.start()
    logger.info("Scheduler started")

    # ── Запуск (polling или webhook) + кнопка меню ──
    if bot is not None:
        if settings.webhook_mode:
            webhook_url = f"{settings.base_url}/api/webhook"
            await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            await _setup_menu_button(bot)
            logger.info(f"Bot webhook set: {webhook_url}")
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            await _setup_menu_button(bot)
            asyncio.create_task(dp.start_polling(bot))
            logger.info("Bot polling started")

    mode_label = "webhook (облако)" if settings.webhook_mode else "polling (автономный)"
    print(BANNER.format(mode=mode_label), flush=True)
    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║        🏠  УМНЫЙ ДОМ — БОТ ЗАПУЩЕН!         ║")
    logger.info("╚══════════════════════════════════════════════╝")

    yield

    # ── Остановка ──
    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    if bot is not None:
        try:
            if settings.webhook_mode:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("Webhook deleted")
            else:
                await dp.stop_polling()
                logger.info("Polling stopped")
        except Exception:
            pass
        await bot.session.close()
    logger.info("Shutdown complete")


app = FastAPI(title="Smart Home Bot", lifespan=lifespan)

# CORS middleware — разрешаем запросы с Cloudflare-туннеля и Telegram Web App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security Headers Middleware ────────────────────────────────

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    return response

# Статика (Frontend Mini App)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Health Check (для Render и мониторинга) ──────────────────────

@app.get("/health")
async def health():
    import platform
    from database import DB_PATH

    db_exists = DB_PATH.exists()
    db_size = DB_PATH.stat().st_size if db_exists else 0

    return {
        "status": "ok",
        "mode": "webhook" if settings.webhook_mode else "polling",
        "python": platform.python_version(),
        "db": {
            "exists": db_exists,
            "size_bytes": db_size,
            "path": str(DB_PATH),
        },
        "services": {
            "tuya": bool(settings.tuya_access_id and settings.tuya_secret),
            "rutracker": bool(
                settings.rutracker_user or os.getenv("RUTRACKER_USER")
            ) and bool(
                settings.rutracker_pass or os.getenv("RUTRACKER_PASS")
            ),
            "qbittorrent": bool(settings.pc_ip),
        },
    }


def _ssh_known_hosts() -> str | None:
    path = os.path.expanduser("~/.ssh/known_hosts")
    return path if os.path.isfile(path) else None

# API роутер (включает /api/webhook)
from api.api import router as api_router

app.include_router(api_router)


# ── Rate Limiting Middleware ───────────────────────────────────

_rate_limits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 60


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    window = _rate_limits[client_ip]
    window[:] = [t for t in window if now - t < RATE_LIMIT_WINDOW]

    if len(window) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many requests")

    window.append(now)
    response = await call_next(request)
    return response


# ── Sisyphus Auth Dependency ──────────────────────────────────

async def verify_sisyphus_key(
    x_sisyphus_api_key: str = Header(..., alias="X-Sisyphus-API-Key"),
) -> str:
    expected = settings.sisyphus_api_key
    if not expected:
        raise HTTPException(status_code=501, detail="SISYPHUS_API_KEY not configured")
    if x_sisyphus_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_sisyphus_api_key


# ── Sisyphus Status (оповещение о завершении работы) ────────────
sisyphus_status = {"status": "idle", "message": ""}


@app.get("/api/sisyphus-status")
async def get_sisyphus_status(
    api_key: str = Depends(verify_sisyphus_key),
):
    """Возвращает текущий статус: idle / working / done."""
    return sisyphus_status


@app.post("/api/sisyphus-status/done")
async def set_sisyphus_done(
    message: str = "✅ Задача выполнена!",
    api_key: str = Depends(verify_sisyphus_key),
):
    """Установить статус 'done' — сыграть звук на Windows через SSH + watcher fallback."""
    sisyphus_status["status"] = "done"
    sisyphus_status["message"] = message

    # Fire-and-forget: попробовать сыграть звук на Windows ПК через SSH
    asyncio.create_task(_notify_pc_sound(message))

    return sisyphus_status


async def _notify_pc_sound(message: str) -> None:
    ip = settings.pc_ip
    user = settings.pc_user
    if not ip or not user:
        return
    # Санитизация: разрешены только буквы, цифры, пробелы и базовая пунктуация.
    # Опасные для PowerShell/cmd символы удаляются.
    safe_message = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9 .,!?:\-()@#№%+=\"/\\\\]+", "", message)[:200]
    if not safe_message:
        safe_message = "Задача выполнена!"
    ps_command = (
        'powershell -Command "'
        '$wshell = New-Object -ComObject Wscript.Shell; '
        '$wshell.Popup(\'{}\', 0, \'Sisyphus — Готово!\', 0x40 + 0x1000); '
        '(New-Object Media.SoundPlayer \'C:\\Windows\\Media\\Windows Exclamation.wav\').PlaySync()'
        '"'
    ).format(safe_message.replace("'", "''"))
    try:
        async with asyncssh.connect(
            ip,
            username=user,
            client_keys=[settings.ssh_key_path],
            known_hosts=_ssh_known_hosts(),
            connect_timeout=5,
        ) as conn:
            await conn.run(ps_command, timeout=10)
            logger.info(f"PC notification sent: {message}")
    except FileNotFoundError:
        pass  # ключа нет — мы в облаке, это нормально
    except (asyncssh.Error, OSError, asyncio.TimeoutError) as e:
        logger.warning(f"PC notification failed (PC offline?): {e}")


@app.post("/api/sisyphus-status/working")
async def set_sisyphus_working(
    message: str = "",
    api_key: str = Depends(verify_sisyphus_key),
):
    """Установить статус 'working' — перед началом задачи."""
    sisyphus_status["status"] = "working"
    sisyphus_status["message"] = message
    return sisyphus_status


@app.post("/api/sisyphus-status/idle")
async def set_sisyphus_idle(
    api_key: str = Depends(verify_sisyphus_key),
):
    """Сбросить статус в idle — после того как уведомление получено."""
    sisyphus_status["status"] = "idle"
    sisyphus_status["message"] = ""
    return sisyphus_status


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
