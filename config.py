"""
Настройки приложения из переменных окружения (.env).
BASE_URL задаётся динамически скриптом start.sh (URL Cloudflare-туннеля).
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    weather_api_key: str = field(default_factory=lambda: os.getenv("WEATHER_API_KEY", "").strip())
    weather_city: str = field(default_factory=lambda: os.getenv("WEATHER_CITY", "Mogilev").strip())
    tuya_access_id: str = field(default_factory=lambda: os.getenv("TUYA_ACCESS_ID", "").strip())
    tuya_secret: str = field(default_factory=lambda: os.getenv("TUYA_SECRET", "").strip())
    tuya_device_id: str = field(default_factory=lambda: os.getenv("TUYA_DEVICE_ID", "").strip())
    tuya_region_url: str = field(
        default_factory=lambda: os.getenv("TUYA_REGION_URL", "https://openapi.tuyaeu.com").strip()
    )
    pc_ip: str = field(default_factory=lambda: os.getenv("PC_IP", "").strip())
    pc_user: str = field(default_factory=lambda: os.getenv("PC_USER", "").strip())
    pc_password: str = field(default_factory=lambda: os.getenv("PC_PASSWORD", "").strip())
    pc_mac: str = field(default_factory=lambda: os.getenv("PC_MAC", "").strip())

    # rutracker credentials
    rutracker_user: str = field(default_factory=lambda: os.getenv("RUTRACKER_USER", "").strip())
    rutracker_pass: str = field(default_factory=lambda: os.getenv("RUTRACKER_PASS", "").strip())

    # qBittorrent credentials
    qb_user: str = field(default_factory=lambda: os.getenv("QB_USER", "").strip())
    qb_pass: str = field(default_factory=lambda: os.getenv("QB_PASS", "").strip())

    # SSH
    ssh_key_path: str = field(default_factory=lambda: os.getenv("SSH_KEY_PATH", "/root/.ssh/id_rsa").strip())

    # Access control
    allowed_users: str = field(default_factory=lambda: os.getenv("ALLOWED_USERS", "").strip())
    sisyphus_api_key: str = field(default_factory=lambda: os.getenv("SISYPHUS_API_KEY", "").strip())

    # Режим работы: webhook (для облака) или polling (для локалки)
    webhook_mode: bool = field(
        default_factory=lambda: os.getenv("WEBHOOK_MODE", "").strip().lower() in ("1", "true", "yes")
    )

    @property
    def allowed_user_ids(self) -> set[int]:
        raw = self.allowed_users
        if not raw:
            return set()
        return {int(uid.strip()) for uid in raw.split(",") if uid.strip().isdigit()}

    @property
    def base_url(self) -> str:
        """Базовый URL приложения. Берётся из BASE_URL или RENDER_EXTERNAL_URL (Render)."""
        url = os.getenv("BASE_URL", "").strip()
        if not url:
            url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
        return url or "http://localhost:8000"

    @property
    def webapp_url(self) -> str:
        """URL мини-приложения (Telegram Mini App)."""
        return f"{self.base_url}/static/index.html"

    @property
    def webhook_url(self) -> str:
        """URL вебхука Telegram для приёма апдейтов."""
        return f"{self.base_url}/api/webhook"


settings = Settings()
