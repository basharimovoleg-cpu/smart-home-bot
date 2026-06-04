"""
Погода через Open-Meteo API (Могилёв: lat=53.90, lon=30.33).
"""

import aiohttp

WMO_CODES: dict[int, str] = {
    0: "☀️ Ясно",
    1: "🌤 Преимущественно ясно",
    2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно",
    45: "🌫 Туман",
    48: "🌫 Иней / туман",
    51: "🌧 Лёгкая морось",
    53: "🌧 Морось",
    55: "🌧 Сильная морось",
    56: "🌧 Ледяная морось",
    57: "🌧 Сильная ледяная морось",
    61: "🌧 Небольшой дождь",
    63: "🌧 Дождь",
    65: "🌧 Сильный дождь",
    66: "🌧 Ледяной дождь",
    67: "🌧 Сильный ледяной дождь",
    71: "🌨 Небольшой снег",
    73: "🌨 Снег",
    75: "🌨 Сильный снег",
    77: "🌨 Снежные зёрна",
    80: "🌧 Ливень",
    81: "🌧 Сильный ливень",
    82: "🌧 Очень сильный ливень",
    85: "🌨 Небольшой снегопад",
    86: "🌨 Сильный снегопад",
    95: "⛈ Гроза",
    96: "⛈ Гроза с градом",
    99: "⛈ Сильная гроза с градом",
}

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=53.90&longitude=30.33"
    "&current=temperature_2m,apparent_temperature,weather_code,precipitation_probability"
    "&daily=temperature_2m_max"
    "&timezone=Europe%2FMinsk"
    "&forecast_days=1"
)


async def fetch_weather() -> dict:
    """Запросить текущую погоду у Open-Meteo."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            OPEN_METEO_URL,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


def format_weather(data: dict) -> str:
    """Преобразовать JSON-ответ Open-Meteo в читаемый текст."""
    current = data.get("current", {})
    daily = data.get("daily", {})

    temp = current.get("temperature_2m", "—")
    feels = current.get("apparent_temperature", "—")
    code = current.get("weather_code", 0)
    precip = current.get("precipitation_probability", "—")

    weather_text = WMO_CODES.get(code, f"⏳ Код {code}")

    max_temps = daily.get("temperature_2m_max", [])
    max_temp = max_temps[0] if max_temps else "—"

    return (
        f"🌤 *Погода в Могилёве сейчас*\n\n"
        f"{weather_text}\n"
        f"🌡 Температура: *{temp}°C*\n"
        f"🤔 Ощущается: *{feels}°C*\n"
        f"📈 Макс. за день: *{max_temp}°C*\n"
        f"💧 Вероятность дождя: *{precip}%*"
    )