import logging
import json
import os

import aiohttp
from config import settings

logger = logging.getLogger("qb_client")

QB_URL = f"http://{settings.pc_ip}:8080" if settings.pc_ip else ""
QB_USER = settings.qb_user
QB_PASS = settings.qb_pass
MOVIES_PATH = "D:\\Фильмы"
SERIES_PATH = "D:\\Сериалы"


class QbClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._sid: str = ""
        self._available: bool | None = None  # None = не проверяли

    @property
    def available(self) -> bool:
        """Доступен ли qBittorrent (определяется при первом login)."""
        if self._available is None:
            return bool(settings.pc_ip)  # оптимистично: если IP задан — пробуем
        return self._available

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    def _headers(self) -> dict:
        h = {"Referer": f"{QB_URL}/"}
        if self._sid:
            h["Cookie"] = f"SID={self._sid}"
        return h

    async def login(self) -> bool:
        if not QB_URL:
            logger.info("qBittorrent: PC_IP not set — skipping (cloud mode)")
            self._available = False
            return False

        await self._ensure_session()
        try:
            resp = await self._session.post(
                f"{QB_URL}/api/v2/auth/login",
                data={"username": QB_USER, "password": QB_PASS},
                headers={"Referer": f"{QB_URL}/"},
                timeout=aiohttp.ClientTimeout(total=5),
            )
            text = await resp.text()
            if text.strip() == "Ok.":
                for cookie in resp.cookies.values():
                    if cookie.key == "SID":
                        self._sid = cookie.value
                        break
                logger.info(f"qBittorrent login OK, SID={'***' if self._sid else 'NONE'}")
                self._available = True
                resp.release()
                return bool(self._sid)
            resp.release()
            logger.warning(f"qBittorrent login failed: {text.strip()}")
            self._available = False
            return False
        except Exception as e:
            logger.warning(f"qBittorrent unavailable (PC offline?): {e}")
            self._available = False
            return False

    async def add_torrent_file(self, file_path: str, save_path: str, category: str = "movies") -> dict:
        if not self.available:
            return {"success": False, "error": "qBittorrent unavailable (PC offline or cloud mode)"}

        await self._ensure_session()
        try:
            form = aiohttp.FormData()
            with open(file_path, "rb") as f:
                form.add_field("torrents", f.read(), filename="torrent.torrent",
                               content_type="application/x-bittorrent")
            form.add_field("savepath", save_path)
            form.add_field("category", category)
            form.add_field("paused", "false")

            resp = await self._session.post(
                f"{QB_URL}/api/v2/torrents/add",
                data=form,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            )
            text = await resp.text()
            resp.release()
            if resp.status == 200:
                return {"success": True}
            return {"success": False, "error": text.strip()}
        except Exception as e:
            logger.warning(f"qBittorrent add_torrent_file failed: {e}")
            self._available = False
            return {"success": False, "error": str(e)}

    async def get_torrents(self) -> list[dict]:
        if not self.available:
            return []

        await self._ensure_session()
        try:
            resp = await self._session.get(
                f"{QB_URL}/api/v2/torrents/info",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=5),
            )
            text = await resp.text()
            resp.release()
            if resp.status != 200:
                return []
            data = json.loads(text)
            return [
                {
                    "hash": t.get("hash", ""),
                    "name": t.get("name", ""),
                    "progress": round(t.get("progress", 0) * 100, 1),
                    "state": t.get("state", ""),
                    "size": t.get("size", 0),
                    "dlspeed": t.get("dlspeed", 0),
                    "save_path": t.get("save_path", ""),
                    "category": t.get("category", ""),
                    "added_on": t.get("added_on", 0),
                }
                for t in data
            ]
        except Exception as e:
            logger.error(f"qBittorrent get_torrents failed: {e}")
            return []

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


qb = QbClient()
