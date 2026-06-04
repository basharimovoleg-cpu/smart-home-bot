# 🏗️ Blueprint: Telegram Bot + FastAPI + Mini App

> Шаблон для создания **любого** Telegram-бота с Web Mini App.
> Скопируй структуру → замени бизнес-логику → готово.

---

## 📁 Структура проекта

```
my_bot/
├── .env                    # секреты + WEBAPP_URL
├── .env.example            # образец для репозитория
├── config.py               # pydantic/dataclass Settings из .env
├── main.py                 # точка входа: FastAPI + aiogram (lifespan)
├── database.py             # aiosqlite: init_db() + CRUD-функции
├── requirements.txt        # зависимости
├── start.sh                # быстрый запуск (опционально)
│
├── bot/                    # логика Telegram-бота
│   ├── __init__.py
│   └── bot.py              # create_bot(), handlers, клавиатуры
│
├── api/                    # FastAPI роутер для Mini App
│   └── api.py              # APIRouter, модели Pydantic, эндпоинты
│
└── static/                 # фронтенд Mini App (HTML/CSS/JS)
    ├── index.html          # подключает telegram-web-app.js
    ├── style.css           # стили
    └── app.js              # логика: вызов API через fetch + initData
```

---

## 🔌 main.py — сердце проекта

```python
# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. init_db() — поднять таблицы
    # 2. create_bot() — бот + dp (aiogram)
    # 3. scheduler (apscheduler) — если нужен
    # 4. dp.start_polling(bot) — asyncio.create_task
    # 5. set_chat_menu_button — кнопка "Открыть Mini App"
    yield
    # shutdown: scheduler, polling, session

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(api_router)   # из api/api.py

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Ключевой паттерн**: один процесс = FastAPI + aiogram polling.
Не нужно отдельных процессов для сервера и бота.

---

## ⚙️ config.py — настройки

```python
from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    webapp_url: str = field(default_factory=lambda: os.getenv("WEBAPP_URL", ""))
    # ... добавь свои переменные

settings = Settings()
```

---

## 🗄️ database.py — БД на aiosqlite

```python
import aiosqlite

DB_PATH = Path(__file__).parent / "data" / "bot.db"

async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    db = await get_db()
    await db.execute("CREATE TABLE IF NOT EXISTS ...")
    await db.commit()
    await db.close()

# + CRUD-функции: add_*, get_*, update_*, delete_*
```

Паттерн каждой функции:
```python
async def my_crud(...):
    db = await get_db()
    try:
        # работа с db
        await db.commit()
        return result
    finally:
        await db.close()
```

---

## 🤖 bot/bot.py — Telegram-бот (aiogram 3.x)

```python
from aiogram import Bot, Dispatcher, Router
from config import settings

router = Router()   # или несколько роутеров

@router.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📱 Открыть приложение",
            web_app=WebAppInfo(url=settings.webapp_url),
        )
    ]])
    await message.answer("Привет!", reply_markup=kb)

def create_bot() -> Bot:
    bot = Bot(token=settings.bot_token)
    dp.include_router(router)
    return bot

dp = Dispatcher()
```

---

## 🌐 api/api.py — FastAPI для Mini App

```python
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
import hmac, hashlib, json
from urllib.parse import parse_qs

router = APIRouter(prefix="/api")

# 🔐 Валидация initData (ОБЯЗАТЕЛЬНО!)
async def get_current_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
) -> dict:
    parsed_qs = parse_qs(x_telegram_init_data)
    parsed = {k: v[0] for k, v in parsed_qs.items()}
    received_hash = parsed.pop("hash", None)

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )
    secret_key = hmac.new(
        b"WebAppData", settings.bot_token.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if computed_hash != received_hash:
        raise HTTPException(status_code=401)

    user = json.loads(parsed.get("user", "{}"))
    return {"user_id": user["id"], "user": user}

# 📡 Эндпоинты используют Depends(get_current_user)
@router.get("/example")
async def example(auth: dict = Depends(get_current_user)):
    user_id = auth["user_id"]
    return {"ok": True, "user_id": user_id}
```

---

## 🎨 static/ — Mini App фронтенд

### index.html (шаблон)
```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div id="app">...</div>
    <script src="/static/app.js"></script>
</body>
</html>
```

### app.js (шаблон вызова API)
```javascript
const tg = window.Telegram.WebApp;

async function apiCall(endpoint, options = {}) {
    const url = `/api${endpoint}`;
    const res = await fetch(url, {
        ...options,
        headers: {
            'X-Telegram-Init-Data': tg.initData,  // ← ключевой заголовок
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
}

// Использование:
// const data = await apiCall('/weather');
```

---

## 📦 requirements.txt

```
fastapi
uvicorn[standard]
aiogram
aiosqlite
apscheduler         # если нужен планировщик
aiohttp
python-dotenv
```

---

## 🚀 Запуск

### 1. Локально
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. С туннелем Cloudflare (для Mini App)
```bash
# Терминал 1
uvicorn main:app --host 0.0.0.0 --port 8000

# Терминал 2
cloudflared tunnel --url http://127.0.0.1:8000
# Скопировать URL вида https://....trycloudflare.com
# Прописать в .env:
#   WEBAPP_URL=https://....trycloudflare.com/static/index.html
# Перезапустить uvicorn
```

### 3. Скрипт start.sh (для удобства)
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 kill_port.py 8000 2>/dev/null || true
sleep 1
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 🧩 Что заменить под свой проект

| Компонент | Что менять |
|---|---|
| `bot/bot.py` | Хендлеры, клавиатуры, бизнес-логику бота |
| `api/api.py` | Эндпоинты API, Pydantic-модели |
| `static/index.html` | UI блоки, заголовки |
| `static/app.js` | Вызовы API, DOM-логику |
| `database.py` | Схему таблиц, CRUD под свои сущности |
| `config.py` / `.env` | Переменные окружения |
| `main.py` | Lifespan (инициализацию), если нужны другие модули |

---

## ✅ Чек-лист: что не забыть

- [ ] `.env` — `BOT_TOKEN`, `WEBAPP_URL`
- [ ] `.env.example` — образец без секретов, добавить в git
- [ ] `WEBAPP_URL` заканчивается на `/static/index.html`
- [ ] Каждый эндпоинт API защищён `Depends(get_current_user)`
- [ ] `get_current_user` валидирует `initData` через HMAC-SHA256
- [ ] Frontend передаёт `X-Telegram-Init-Data: tg.initData`
- [ ] `user-scalable=no` в мете (чтобы не зумился в Telegram)
- [ ] `MenuButtonWebApp` в `lifespan` для кнопки в меню бота
- [ ] При смене туннеля — обновить `.env` и перезапустить сервер
