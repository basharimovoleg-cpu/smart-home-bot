"""
Вспомогательный скрипт: обновление webhook и кнопки меню Telegram.
Вызывается из start.sh после получения URL Cloudflare-туннеля.

Использование: python3 setup_telegram.py <BASE_URL>
"""
import asyncio
import sys

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo
from config import settings

MAX_RETRIES = 7
RETRY_DELAY = 5   # секунд между попытками


def _is_dns_error(error: Exception) -> bool:
    """Проверяет, связана ли ошибка Telegram API с неразрешённым DNS."""
    msg = str(error).lower()
    return any(kw in msg for kw in (
        "failed to resolve",
        "name or service not known",
        "bad webhook",
        "resolve host",
        "temporary failure",
    ))


async def _set_webhook_with_retry(bot: Bot, webhook_url: str) -> None:
    """Установить webhook с повторными попытками при DNS-ошибках."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(webhook_url)
            print(f"  Webhook установлен: {webhook_url}")
            return  # успех — выходим
        except Exception as e:
            if _is_dns_error(e):
                if attempt < MAX_RETRIES:
                    print(f"  ⚠ DNS ещё не пропагирован (попытка {attempt}/{MAX_RETRIES}),"
                          f" жду {RETRY_DELAY} сек...")
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                else:
                    print(f"  ❌ Webhook не установлен после {MAX_RETRIES} попыток: {e}")
                    raise
            else:
                # не DNS-ошибка — не ретраим
                print(f"  ❌ Ошибка webhook: {e}")
                raise


async def setup_telegram(base_url: str) -> None:
    """Установить webhook и кнопку меню через Telegram Bot API."""
    base = base_url.rstrip("/")
    webhook_url = f"{base}/api/webhook"
    webapp_url = f"{base}/static/index.html"

    bot = Bot(token=settings.bot_token)

    # 1. Webhook (с retry-логикой для DNS)
    try:
        await _set_webhook_with_retry(bot, webhook_url)
    except Exception:
        await bot.session.close()
        sys.exit(1)

    # 2. Menu button (Mini App)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Умный Дом",
                web_app=WebAppInfo(url=webapp_url),
            )
        )
        print(f"  Menu button установлен: {webapp_url}")
    except Exception as e:
        print(f"  ❌ Ошибка menu button: {e}")

    await bot.session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 setup_telegram.py <BASE_URL>")
        sys.exit(1)
    base_url = sys.argv[1]
    asyncio.run(setup_telegram(base_url))
