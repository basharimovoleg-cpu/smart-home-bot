"""
HTTP-клиент для Tuya Cloud OpenAPI (v1.0).
Алгоритм подписи — по официальной документации / Python SDK.
"""

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class TuyaConfig:
    access_id: str
    secret: str
    device_id: str
    base_url: str


class TuyaClient:
    """Обёртка над Tuya Cloud OpenAPI."""

    TOKEN_PATH = "/v1.0/token"

    def __init__(self, config: TuyaConfig) -> None:
        self._cfg = config
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expires_at: int = 0  # unix ms

    # ── подпись (официальный алгоритм из SDK) ─────────────

    def _calc_sign(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Вернуть (sign, timestamp_ms)."""

        # 1. HTTPMethod
        str_to_sign = method.upper()

        # 2. Content-SHA256
        body_str = json.dumps(body) if body else ""
        body_sha = hashlib.sha256(body_str.encode()).hexdigest().lower()
        str_to_sign += "\n" + body_sha

        # 3. Headers (пусто — кастомных не добавляем)
        str_to_sign += "\n"

        # 4. URL = path + ?query
        str_to_sign += "\n" + path
        if params:
            keys = sorted(params.keys())
            query = "?" + "&".join(f"{k}={params[k]}" for k in keys)
            str_to_sign += query

        # 5. Сборка сообщения
        t = str(int(time.time() * 1000))
        message = self._cfg.access_id
        if self._access_token:
            message += self._access_token
        message += t + str_to_sign

        sign = hmac.new(
            self._cfg.secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        return sign, t

    # ── HTTP-запрос ───────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict:
        """Выполнить подписанный запрос к Tuya Cloud."""

        # Авто-обновление токена если нужно
        if self._access_token and not path.startswith(self.TOKEN_PATH):
            now_ms = int(time.time() * 1000)
            if now_ms >= self._token_expires_at - 60_000:
                self._do_refresh_token()

        sign, t = self._calc_sign(method, path, params, body)

        headers = {
            "client_id": self._cfg.access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
        }
        if self._access_token:
            headers["access_token"] = self._access_token

        url = f"{self._cfg.base_url}{path}"
        resp = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=body,
            timeout=15,
        )
        data = resp.json()

        if not data.get("success"):
            code = data.get("code")
            # token expired — пробуем обновить и повторить
            if code == 1010 and not path.startswith(self.TOKEN_PATH):
                self._do_refresh_token()
                return self._request(method, path, params, body)
            raise TuyaError(
                f"Tuya API error: code={code}, msg={data.get('msg')}",
                code=code,
            )
        return data

    # ── токены ────────────────────────────────────────────

    def _do_fetch_token(self) -> None:
        """Получить новый токен (без refresh_token)."""
        now_ms = int(time.time() * 1000)
        sign, t = self._calc_sign("GET", self.TOKEN_PATH, params={"grant_type": "1"})
        headers = {
            "client_id": self._cfg.access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
        }

        resp = requests.get(
            f"{self._cfg.base_url}{self.TOKEN_PATH}",
            headers=headers,
            params={"grant_type": "1"},
            timeout=15,
        )
        data = resp.json()
        if not data.get("success"):
            raise TuyaError(
                f"Token fetch failed: code={data.get('code')}, msg={data.get('msg')}",
                code=data.get("code"),
            )

        result = data["result"]
        self._access_token = result["access_token"]
        self._refresh_token = result.get("refresh_token", "")
        expire_sec = result.get("expire_time", result.get("expire", 7200))
        self._token_expires_at = now_ms + expire_sec * 1000

    def _do_refresh_token(self) -> None:
        """Обновить токен через refresh_token."""
        if not self._refresh_token:
            self._do_fetch_token()
            return

        now_ms = int(time.time() * 1000)
        path = f"{self.TOKEN_PATH}/{self._refresh_token}"
        sign, t = self._calc_sign("GET", path)
        headers = {
            "client_id": self._cfg.access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
        }

        resp = requests.get(
            f"{self._cfg.base_url}{path}",
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        if not data.get("success"):
            # если refresh не удался — пробуем новый токен
            self._do_fetch_token()
            return

        result = data["result"]
        self._access_token = result["access_token"]
        self._refresh_token = result.get("refresh_token", "")
        expire_sec = result.get("expire_time", result.get("expire", 7200))
        self._token_expires_at = now_ms + expire_sec * 1000

    def _ensure_token(self) -> None:
        """Гарантировать наличие токена."""
        if self._access_token:
            return
        self._do_fetch_token()

    # ── устройство ──────────────────────────────────────────

    def get_device_status(self) -> dict[str, Any]:
        """Получить статус устройства (все DP)."""
        self._ensure_token()
        dev_id = self._cfg.device_id
        return self._request("GET", f"/v1.0/iot-03/devices/{dev_id}/status")

    def send_commands(self, commands: list[dict]) -> dict:
        """Отправить команды на устройство.

        commands – список вида [{"code": "switch_1", "value": True}, ...]
        """
        self._ensure_token()
        dev_id = self._cfg.device_id
        return self._request(
            "POST",
            f"/v1.0/iot-03/devices/{dev_id}/commands",
            body={"commands": commands},
        )


class TuyaError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code