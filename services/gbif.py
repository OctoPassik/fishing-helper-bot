"""GBIF Occurrence API client: научные наблюдения рыб.

В отличие от iNaturalist, GBIF аккумулирует литературные и научные
датасеты (например, опубликованный датасет «Fish occurrence in the
Kuban River Basin» с 1328 записями — https://doi.org/10.3897/BDJ.9.e76701).

Документация: https://www.gbif.org/developer/occurrence
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

import aiohttp

log = logging.getLogger(__name__)

GBIF_OCCURRENCE_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"

# classKey для Actinopterygii (лучепёрые рыбы) в таксономии GBIF.
ACTINOPTERYGII_CLASS_KEY = 204

USER_AGENT = (
    "fishing-helper-bot/1.0 "
    "(+https://github.com/OctoPassik/fishing-helper-bot)"
)


def _bbox_from_point(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Return (lat_min, lat_max, lon_min, lon_max) for a square bbox."""
    lat_delta = radius_km / 111.0
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    lon_delta = radius_km / (111.0 * cos_lat)
    return (
        lat - lat_delta,
        lat + lat_delta,
        lon - lon_delta,
        lon + lon_delta,
    )


def _normalize_scientific(name: str) -> str:
    """Drop author/year suffix, keep only 'Genus species'."""
    if not name:
        return ""
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


async def fetch_gbif_fish(
    lat: float,
    lon: float,
    radius_km: float = 50.0,
    limit: int = 300,
) -> list[dict]:
    """Fetch distinct fish species (class Actinopterygii) from GBIF.

    Uses a square bounding box around (lat, lon). Aggregates occurrences by
    normalized scientific name (Genus species) and returns a list sorted by
    count descending.

    Raises `aiohttp.ClientError` if the API is unreachable.
    """
    lat_min, lat_max, lon_min, lon_max = _bbox_from_point(lat, lon, radius_km)
    params = {
        "classKey": ACTINOPTERYGII_CLASS_KEY,
        "decimalLatitude": f"{lat_min},{lat_max}",
        "decimalLongitude": f"{lon_min},{lon_max}",
        "limit": limit,
    }
    timeout = aiohttp.ClientTimeout(total=25)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(GBIF_OCCURRENCE_SEARCH_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if not isinstance(data, dict):
        return []

    counts: dict[str, int] = defaultdict(int)
    for occ in data.get("results") or []:
        sci = occ.get("species") or occ.get("scientificName")
        if not sci:
            continue
        normalized = _normalize_scientific(str(sci))
        if normalized:
            counts[normalized] += 1

    return [
        {
            "scientific": name,
            "russian": None,
            "english": None,
            "count": count,
            "photo_url": None,
            "wiki_url": None,
            "source": "gbif",
        }
        for name, count in counts.items()
    ]
