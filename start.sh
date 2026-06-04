#!/bin/bash
# =============================================
#  УМНЫЙ ДОМ — автоматический запуск
#  Cloudflare tunnel → парсинг URL → Telegram → uvicorn
# =============================================
set -e
cd /workspace/Desktop/Projects/smart_home_bot

# ── Загружаем .env ────────────────────────────────────────
set -a
source .env
set +a

# ── Остановка старых процессов ────────────────────────────
echo ">>> Остановка старых процессов..."
python3 kill_port.py 8000 2>/dev/null || true
python3 kill_main.py 2>/dev/null || true
pkill -9 -f uvicorn 2>/dev/null || true
pkill -9 -f cloudflared 2>/dev/null || true
fuser -k 8000/tcp 2>/dev/null || true
sleep 2

# ── Запуск Cloudflare туннеля ─────────────────────────────
echo ">>> Запуск Cloudflare туннеля..."
CLOUDFLARE_LOG="/tmp/cloudflare_smart_home.log"
rm -f "$CLOUDFLARE_LOG"                          # принудительная очистка старых логов
cloudflared tunnel --url http://localhost:8000 --no-autoupdate > "$CLOUDFLARE_LOG" 2>&1 &
CLOUDFLARED_PID=$!

# ── Ожидание URL ──────────────────────────────────────────
echo ">>> Ожидание URL туннеля..."
TUNNEL_URL=""
MAX_WAIT=60
for i in $(seq 1 $MAX_WAIT); do
    sleep 1
    # Ищем строку с trycloudflare.com URL (только свеже-сгенерированный)
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$CLOUDFLARE_LOG" 2>/dev/null | tail -1)
    if [ -n "$TUNNEL_URL" ]; then
        echo ""
        echo "  ✅ Найден новый URL туннеля: $TUNNEL_URL"
        break
    fi
    printf "."
done

if [ -z "$TUNNEL_URL" ]; then
    echo ""
    echo "❌ Не удалось получить URL туннеля за ${MAX_WAIT} секунд"
    echo "=== Лог cloudflared ==="
    cat "$CLOUDFLARE_LOG"
    exit 1
fi

# ── Пауза для пропагации DNS Cloudflare ───────────────────
echo ">>> Ожидание пропагации DNS (10 сек)..."
sleep 10

# ── Обновление Telegram (webhook + menu button) ───────────
echo ">>> Обновление Telegram (webhook + menu button)..."
export BASE_URL="$TUNNEL_URL"
python3 setup_telegram.py "$TUNNEL_URL"
if [ $? -ne 0 ]; then
    echo "❌ Ошибка обновления Telegram API"
    exit 1
fi

# ── Запуск сервера ────────────────────────────────────────
echo ">>> Запуск uvicorn (webhook-режим)..."
echo "    BASE_URL=$TUNNEL_URL"
echo "    Webhook:  $TUNNEL_URL/api/webhook"
echo "    Mini App: $TUNNEL_URL/static/index.html"
echo ""

exec uvicorn main:app --host :: --port 8000
