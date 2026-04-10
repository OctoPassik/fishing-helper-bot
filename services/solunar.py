"""Solunar API client: фаза луны и периоды активности клёва."""
from __future__ import annotations

import datetime as _dt

import aiohttp

# URL format: lat,lon (decimal degrees), date (YYYYMMDD), tz (signed int UTC hours).
# Example: .../45.04,38.98,20260410,3  or  .../40.71,-74.00,20260410,-5
SOLUNAR_URL_FMT = "https://api.solunar.org/solunar/{lat},{lon},{date},{tz}"
USER_AGENT = "fishing-helper-bot/1.0 (+https://github.com/OctoPassik/fishing-helper-bot)"


async def fetch_solunar(
    lat: float,
    lon: float,
    d: _dt.date,
    tz_offset: int,
) -> dict:
    """Fetch solunar data for a date at given coords.

    `tz_offset` is a signed integer UTC offset in hours
    (e.g. 3 for MSK, -5 for EST).
    Returns the raw JSON dict (keys like `moonPhase`, `major1Start`, etc.).
    """
    url = SOLUNAR_URL_FMT.format(
        lat=f"{float(lat):.4f}",
        lon=f"{float(lon):.4f}",
        date=d.strftime("%Y%m%d"),
        tz=int(tz_offset),
    )
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Solunar API вернул не-dict: {type(data).__name__}")
    return data


_MOON_PHASE_RU = {
    "New": "новолуние 🌑",
    "New Moon": "новолуние 🌑",
    "Waxing Crescent": "растущий серп 🌒",
    "First Quarter": "первая четверть 🌓",
    "Waxing Gibbous": "растущая луна 🌔",
    "Full": "полнолуние 🌕",
    "Full Moon": "полнолуние 🌕",
    "Waning Gibbous": "убывающая луна 🌖",
    "Last Quarter": "последняя четверть 🌗",
    "Third Quarter": "последняя четверть 🌗",
    "Waning Crescent": "убывающий серп 🌘",
}


def moon_phase_ru(phase: str | None) -> str:
    if not phase:
        return "—"
    return _MOON_PHASE_RU.get(phase.strip(), phase)
