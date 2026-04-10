"""Поиск ближайшего водоёма через Overpass API (OpenStreetMap)."""
from __future__ import annotations

import math

import aiohttp

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
)

_QUERY_TMPL = """
[out:json][timeout:25];
(
  way(around:5000,{lat},{lon})["waterway"~"river|stream|canal"];
  way(around:5000,{lat},{lon})["natural"="water"];
  relation(around:5000,{lat},{lon})["natural"="water"];
);
out center tags 40;
""".strip()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dla = math.radians(lat2 - lat1)
    dlo = math.radians(lon2 - lon1)
    a = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _human_type(tags: dict) -> str:
    waterway = tags.get("waterway")
    if waterway == "river":
        return "река"
    if waterway == "canal":
        return "канал"
    if waterway == "stream":
        return "ручей"
    if tags.get("natural") == "water":
        water_kind = tags.get("water")
        return {
            "lake": "озеро",
            "reservoir": "водохранилище",
            "pond": "пруд",
            "lagoon": "лиман",
            "oxbow": "старица",
            "river": "река",
            "stream_pool": "затон",
        }.get(water_kind or "", "водоём")
    return "водоём"


async def find_nearest_water(lat: float, lon: float) -> dict | None:
    """Return nearest named water body within ~5 km or None."""
    query = _QUERY_TMPL.format(lat=lat, lon=lon)
    timeout = aiohttp.ClientTimeout(total=30)
    data = None
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in OVERPASS_ENDPOINTS:
            try:
                async with session.post(url, data={"data": query}) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    break
            except Exception:
                continue

    if not data:
        return None

    best = None
    best_score = -1e9
    for el in data.get("elements", []) or []:
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue  # берём только именованные водоёмы

        if "center" in el:
            elat = el["center"]["lat"]
            elon = el["center"]["lon"]
        elif "lat" in el and "lon" in el:
            elat = el["lat"]
            elon = el["lon"]
        else:
            continue

        dist_km = _haversine_km(lat, lon, elat, elon)

        score = 0.0
        waterway = tags.get("waterway")
        if tags.get("natural") == "water":
            water_kind = tags.get("water") or ""
            if water_kind in ("lake", "reservoir"):
                score += 6
            elif water_kind == "pond":
                score += 4
            else:
                score += 3
        if waterway == "river":
            score += 5
        elif waterway in ("canal", "stream"):
            score += 2

        # чем ближе — тем лучше (1 км = −1 балл)
        score -= dist_km

        if score > best_score:
            best_score = score
            best = {
                "name": name,
                "type": _human_type(tags),
                "distance_km": round(dist_km, 2),
                "lat": elat,
                "lon": elon,
                "tags": tags,
            }
    return best
