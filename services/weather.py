"""Open-Meteo client: погода по координатам без API-ключа."""
from __future__ import annotations

import aiohttp

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → русское описание + эмодзи
WEATHER_CODE_RU: dict[int, str] = {
    0: "ясно ☀️",
    1: "в основном ясно 🌤",
    2: "переменная облачность ⛅",
    3: "пасмурно ☁️",
    45: "туман 🌫",
    48: "изморозь 🌫",
    51: "лёгкая морось 🌦",
    53: "морось 🌦",
    55: "сильная морось 🌧",
    56: "ледяная морось 🌧",
    57: "сильная ледяная морось 🌧",
    61: "небольшой дождь 🌦",
    63: "дождь 🌧",
    65: "сильный дождь 🌧",
    66: "ледяной дождь 🌧",
    67: "сильный ледяной дождь 🌧",
    71: "небольшой снег 🌨",
    73: "снег 🌨",
    75: "сильный снег ❄️",
    77: "снежная крупа ❄️",
    80: "ливень 🌧",
    81: "сильный ливень 🌧",
    82: "очень сильный ливень ⛈",
    85: "снегопад 🌨",
    86: "сильный снегопад ❄️",
    95: "гроза ⛈",
    96: "гроза с градом ⛈",
    99: "сильная гроза с градом ⛈",
}


async def fetch_weather(lat: float, lon: float) -> dict:
    """Fetch current + hourly + daily weather from Open-Meteo.

    Returns the full API response dict with two derived fields added to
    `current`:
      - `surface_pressure_mmhg`: pressure converted to mmHg
      - `weather_desc_ru`: human-readable Russian description
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weather_code",
            "cloud_cover",
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
        ]),
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
            "cloud_cover",
            "surface_pressure",
            "wind_speed_10m",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "sunrise",
            "sunset",
            "precipitation_sum",
            "wind_speed_10m_max",
        ]),
        "wind_speed_unit": "ms",
        "timezone": "auto",
        "forecast_days": 2,
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(OPEN_METEO_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

    current = data.get("current") or {}
    pressure_hpa = current.get("surface_pressure")
    if pressure_hpa is not None:
        current["surface_pressure_mmhg"] = round(pressure_hpa * 0.75006, 1)
    wc = current.get("weather_code")
    if wc is not None:
        current["weather_desc_ru"] = WEATHER_CODE_RU.get(int(wc), "погода не определена")
    data["current"] = current
    return data


def wind_direction_ru(degrees: float | None) -> str:
    """Convert meteo wind direction (degrees) to Russian 8-rhumb label."""
    if degrees is None:
        return "—"
    dirs = ["С", "С-В", "В", "Ю-В", "Ю", "Ю-З", "З", "С-З"]
    ix = int((float(degrees) + 22.5) // 45) % 8
    return dirs[ix]
