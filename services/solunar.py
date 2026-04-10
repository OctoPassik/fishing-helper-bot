"""Solunar API client: фаза луны и периоды активности клёва."""
from __future__ import annotations

import datetime as _dt

import aiohttp

SOLUNAR_URL_FMT = "https://api.solunar.org/solunar/{lat},{lon},{date},{tz}"


async def fetch_solunar(
    lat: float,
    lon: float,
    d: _dt.date,
    tz_offset: int,
) -> dict:
    """Fetch solunar data for a date at given coords.

    `tz_offset` is an integer UTC offset in hours (e.g. 3 for MSK).
    Returns the raw JSON dict (keys like `moonPhase`, `major1Start`, etc.).
    """
    url = SOLUNAR_URL_FMT.format(
        lat=lat,
        lon=lon,
        date=d.strftime("%Y%m%d"),
        tz=tz_offset,
    )
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()


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
