"""
Менеджер устройств — 2-канальный Tuya-выключатель.
Три логические кнопки: «Ободки», «Основной свет», «Всё».
"""

from dataclasses import dataclass
from typing import Any

from tuya_client import TuyaClient, TuyaConfig, TuyaError


@dataclass
class SwitchState:
    obodki: bool = False       # канал 1
    main_light: bool = False   # канал 2

    def all_on(self) -> bool:
        return self.obodki and self.main_light


class DeviceManager:
    """Управление 2-канальным Tuya-выключателем.

    DP-коды определяются автоматически при первом refresh():
    — ищутся коды, содержащие "switch" (например, switch_1, switch_led);
    — иначе берутся первые два числовых/строковых DP.
    Тип значения (bool/int/str) также подстраивается под ответ от устройства.
    """

    def __init__(self, config: TuyaConfig) -> None:
        self._client = TuyaClient(config)
        self.state = SwitchState()
        self._dp_obodki: str | None = None
        self._dp_main_light: str | None = None
        self._value_type: type = bool  # тип, возвращаемый устройством
        self.last_tuya_error: str | None = None  # последняя ошибка от Tuya API

    # ── авто-определение DP ─────────────────────────────────

    def _discover_dps(self, dps: list[dict]) -> None:
        """По ответу статуса определить, какие DP соответствуют каналам.

        Выбирает два нужных DP-кода, а затем определяет тип значения
        (bool / int / str) *только* по выбранным DP — чтобы посторонние
        DP (например, switch_inching со строковым типом) не портили тип.
        """
        dp_map: dict[str, Any] = {str(dp.get("code", "")): dp for dp in dps}

        # Шаг 1: выбрать два DP-кода
        selected: list[str] = []

        # Предпочитаем коды со словом "switch"
        switch_codes = sorted(c for c in dp_map if "switch" in c.lower())
        if len(switch_codes) >= 2:
            selected = switch_codes[:2]      # берём только первые два!

        if not selected:
            # Запасной вариант: числовые коды
            num_codes = sorted(
                (c for c in dp_map if c.isdigit()), key=int
            )
            if len(num_codes) >= 2:
                selected = num_codes[:2]

        if not selected:
            # Последняя надежда: просто первые два любых кода
            all_codes = list(dp_map.keys())
            if len(all_codes) >= 2:
                selected = all_codes[:2]

        if len(selected) >= 2:
            self._dp_obodki = selected[1]
            self._dp_main_light = selected[0]

        # Шаг 2: определить тип значения только по выбранным DP
        if self._dp_obodki:
            val = dp_map[self._dp_obodki].get("value")
            if isinstance(val, bool):
                self._value_type = bool
            elif isinstance(val, int):
                self._value_type = int
            elif isinstance(val, str):
                self._value_type = str

    # ── синхронизация с облаком ─────────────────────────────

    def refresh(self) -> None:
        """Запросить актуальный статус из Tuya и авто-определить DP."""
        import logging
        logger = logging.getLogger(__name__)

        try:
            data = self._client.get_device_status()
            dps = data.get("result", [])

            if self._dp_obodki is None or self._dp_main_light is None:
                self._discover_dps(dps)
                if self._dp_obodki is None or self._dp_main_light is None:
                    logger.warning(
                        "DP discovery failed: not enough DP codes in device status. "
                        "Raw result: %s", dps
                    )

            for dp in dps:
                code = str(dp.get("code", ""))
                value = dp.get("value")
                if code == self._dp_obodki:
                    self.state.obodki = bool(value)
                elif code == self._dp_main_light:
                    self.state.main_light = bool(value)

            # Успех — сбрасываем last error
            self.last_tuya_error = None
        except TuyaError as e:
            self.last_tuya_error = str(e)
            logger.warning("Tuya refresh failed (cached state kept): %s", e)

    def get_raw_status(self) -> dict:
        """Вернуть полный сырой ответ статуса устройства."""
        return self._client.get_device_status()

    def _check_dp_discovered(self) -> None:
        """Проверить, что DP-коды определены. Иначе — TuyaError."""
        if self._dp_obodki is None or self._dp_main_light is None:
            msg = "DP codes not discovered. Проверь TUYA_DEVICE_ID в .env и доступность устройства в сети."
            if self.last_tuya_error:
                msg += f" Последняя ошибка Tuya API: {self.last_tuya_error}"
            raise TuyaError(msg)

    def _send(self, **switches: bool) -> None:
        """Отправить команды и обновить локальный стейт."""
        self._check_dp_discovered()
        commands = []
        for code, value in switches.items():
            # Приводим значение к типу, который ожидает устройство
            typed_value = self._value_type(value)
            commands.append({"code": code, "value": typed_value})
        self._client.send_commands(commands)
        for code, value in switches.items():
            if code == self._dp_obodki:
                self.state.obodki = value
            elif code == self._dp_main_light:
                self.state.main_light = value

    def _dp_keys(self, value: bool):
        """Словарь {dp_obodki: value, dp_main_light: value}."""
        self._check_dp_discovered()
        return {self._dp_obodki: value, self._dp_main_light: value}

    # ── индивидуальное управление ───────────────────────────

    def toggle_obodki(self) -> bool:
        self._check_dp_discovered()
        new_val = not self.state.obodki
        self._send(**{self._dp_obodki: new_val})
        return new_val

    def toggle_main_light(self) -> bool:
        self._check_dp_discovered()
        new_val = not self.state.main_light
        self._send(**{self._dp_main_light: new_val})
        return new_val

    def set_obodki(self, on: bool) -> None:
        self._check_dp_discovered()
        self._send(**{self._dp_obodki: on})

    def set_main_light(self, on: bool) -> None:
        self._check_dp_discovered()
        self._send(**{self._dp_main_light: on})

    # ── всё сразу ───────────────────────────────────────────

    def toggle_all(self) -> bool:
        """Переключает оба канала: если хотя бы один выключен → включить оба, иначе выключить оба."""
        self._check_dp_discovered()
        new_val = not self.state.all_on()
        self._send(**self._dp_keys(new_val))
        return new_val

    def turn_all_on(self) -> None:
        self._check_dp_discovered()
        self._send(**self._dp_keys(True))

    def turn_all_off(self) -> None:
        self._check_dp_discovered()
        self._send(**self._dp_keys(False))