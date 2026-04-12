"""Поиск водоёма через Overpass API (OpenStreetMap).

Трёхуровневая логика:
1. ON_SITE (300 м, out geom) — точная геометрия, point-in-polygon.
   Берём даже безымянный пруд/старицу.
2. NEAREST (5 км, out center tags) — лёгкий запрос, только именованные.
3. WIDE (100 км, out center tags) — если ничего в 5 км, возвращаем список
   крупных именованных водоёмов для выбора пользователем.
"""
from __future__ import annotations

import logging
import math

import aiohttp

log = logging.getLogger(__name__)

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
)

USER_AGENT = "fishing-helper-bot/1.0 (+https://github.com/OctoPassik/fishing-helper-bot)"

ON_SITE_RADIUS_KM = 0.25
ON_SITE_RADIUS_M = 300
SEARCH_RADIUS_M = 5000
WIDE_RADIUS_M = 100_000

# Маленький запрос с геометрией — для on-site detection (300 м)
_QUERY_ONSITE = """
[out:json][timeout:15];
(
  way(around:{r},{lat},{lon})["waterway"];
  way(around:{r},{lat},{lon})["natural"="water"];
  relation(around:{r},{lat},{lon})["natural"="water"];
  node(around:{r},{lat},{lon})["natural"="water"];
);
out geom 40;
""".strip()

# Лёгкий запрос без геометрии — для nearest (5 км)
_QUERY_NEAREST = """
[out:json][timeout:15];
(
  way(around:{r},{lat},{lon})["waterway"~"river|canal"]["name"];
  way(around:{r},{lat},{lon})["natural"="water"]["name"];
  relation(around:{r},{lat},{lon})["natural"="water"]["name"];
  relation(around:{r},{lat},{lon})["waterway"="river"]["name"];
);
out center tags 40;
""".strip()

# Лёгкий запрос для wide search — только крупные именованные relation-ы
# (way-и для 100 км слишком тяжёлые, relation — это реки и крупные озёра)
_QUERY_WIDE = """
[out:json][timeout:20];
(
  relation(around:{r},{lat},{lon})["waterway"="river"]["name"];
  relation(around:{r},{lat},{lon})["natural"="water"]["name"];
);
out center tags 30;
""".strip()


# --------------------------------------------------------------- geometry ---

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dla = math.radians(lat2 - lat1)
    dlo = math.radians(lon2 - lon1)
    a = (
        math.sin(dla / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _point_to_segment_km(
    plat: float, plon: float,
    alat: float, alon: float,
    blat: float, blon: float,
) -> float:
    mean_lat_rad = math.radians((alat + blat) * 0.5)
    kx = 111.320 * math.cos(mean_lat_rad)
    ky = 110.574

    px = (plon - alon) * kx
    py = (plat - alat) * ky
    bx = (blon - alon) * kx
    by = (blat - alat) * ky

    seg_len2 = bx * bx + by * by
    if seg_len2 < 1e-12:
        return math.hypot(px, py)

    t = (px * bx + py * by) / seg_len2
    t = max(0.0, min(1.0, t))

    dx = px - t * bx
    dy = py - t * by
    return math.hypot(dx, dy)


def _min_dist_km_to_ring(plat: float, plon: float, ring: list[dict]) -> float:
    min_d = float("inf")
    n = len(ring)
    if n == 0:
        return min_d
    if n == 1:
        a = ring[0]
        if a.get("lat") is None:
            return min_d
        return _haversine_km(plat, plon, a["lat"], a["lon"])
    for i in range(n - 1):
        a, b = ring[i], ring[i + 1]
        if any(v is None for v in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))):
            continue
        d = _point_to_segment_km(plat, plon, a["lat"], a["lon"], b["lat"], b["lon"])
        if d < min_d:
            min_d = d
    return min_d


def _point_in_ring(lat: float, lon: float, ring: list[dict]) -> bool:
    n = len(ring)
    if n < 3:
        return False
    x, y = lon, lat
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i].get("lon"), ring[i].get("lat")
        xj, yj = ring[j].get("lon"), ring[j].get("lat")
        if xi is None or yi is None or xj is None or yj is None:
            j = i
            continue
        denom = (yj - yi) or 1e-12
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / denom + xi):
            inside = not inside
        j = i
    return inside


def _is_closed(geometry: list[dict]) -> bool:
    if not geometry or len(geometry) < 3:
        return False
    first, last = geometry[0], geometry[-1]
    flat, flon = first.get("lat"), first.get("lon")
    llat, llon = last.get("lat"), last.get("lon")
    if flat is None or llat is None:
        return False
    return abs(flat - llat) < 1e-9 and abs(flon - llon) < 1e-9


def _min_dist_km_to_geometry(lat: float, lon: float, element: dict) -> tuple[float, bool]:
    min_dist = float("inf")
    inside = False

    if "lat" in element and "lon" in element and "geometry" not in element:
        return _haversine_km(lat, lon, element["lat"], element["lon"]), False

    geom = element.get("geometry")
    if geom:
        d = _min_dist_km_to_ring(lat, lon, geom)
        if d < min_dist:
            min_dist = d
        if _is_closed(geom) and _point_in_ring(lat, lon, geom):
            inside = True
            min_dist = 0.0

    for member in element.get("members") or []:
        if member.get("type") != "way":
            continue
        mgeom = member.get("geometry")
        if not mgeom:
            continue
        d = _min_dist_km_to_ring(lat, lon, mgeom)
        if d < min_dist:
            min_dist = d
        role = member.get("role") or "outer"
        if role in ("outer", "") and _is_closed(mgeom) and _point_in_ring(lat, lon, mgeom):
            inside = True
            min_dist = 0.0

    if min_dist == float("inf"):
        return float("inf"), False
    return min_dist, inside


def _dist_to_center(lat: float, lon: float, element: dict) -> float:
    """Distance to element center point (for `out center tags` results)."""
    c = element.get("center")
    if c and c.get("lat") is not None:
        return _haversine_km(lat, lon, c["lat"], c["lon"])
    if element.get("lat") is not None:
        return _haversine_km(lat, lon, element["lat"], element["lon"])
    return float("inf")


# --------------------------------------------------------------- tagging ---

def _human_type(tags: dict) -> str:
    waterway = tags.get("waterway")
    if waterway == "river":
        return "река"
    if waterway == "canal":
        return "канал"
    if waterway == "stream":
        return "ручей"
    if waterway == "ditch":
        return "канава"
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
            "basin": "бассейн",
            "wastewater": "отстойник",
        }.get(water_kind or "", "водоём")
    return "водоём"


def _type_rank(tags: dict) -> int:
    if tags.get("natural") == "water":
        water_kind = tags.get("water") or ""
        if water_kind in ("lake", "reservoir"):
            return 10
        if water_kind == "lagoon":
            return 9
        if water_kind in ("oxbow", "pond"):
            return 7
        if water_kind == "river":
            return 8
        return 5
    waterway = tags.get("waterway")
    if waterway == "river":
        return 9
    if waterway == "canal":
        return 6
    if waterway == "stream":
        return 4
    if waterway == "ditch":
        return 2
    return 3


def _fishable(tags: dict) -> bool:
    if tags.get("water") in ("wastewater", "basin"):
        return False
    if tags.get("intermittent") == "yes" and not tags.get("name"):
        return False
    return True


def _build_result(element: dict, tags: dict, dist_km: float,
                  on_site: bool, inside: bool) -> dict:
    return {
        "name": tags.get("name"),
        "type": _human_type(tags),
        "distance_km": round(dist_km, 3),
        "on_site": on_site,
        "inside": inside,
        "element_type": element.get("type"),
        "tags": tags,
    }


# --------------------------------------------------------------- helpers ---

async def _overpass_query(query: str, timeout_sec: int = 20) -> dict | None:
    """Run an Overpass query, trying all endpoints."""
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for url in OVERPASS_ENDPOINTS:
            try:
                async with session.post(url, data={"data": query}) as resp:
                    if resp.status != 200:
                        log.info("overpass %s: HTTP %s", url, resp.status)
                        continue
                    data = await resp.json()
                    return data
            except Exception as exc:
                log.info("overpass %s failed: %s", url, exc)
                continue
    return None


# --------------------------------------------------------------- main ---

async def find_nearest_water(lat: float, lon: float) -> dict | None:
    """Find water body the user is on, or the nearest named one.

    Two-phase approach to avoid Overpass timeouts:
    1. Small radius (300m) with full geometry for on-site detection
    2. Large radius (5km) with center-only for nearest-named fallback
    """

    # --- Phase 1: on-site (300m, with geometry) ---
    query_small = _QUERY_ONSITE.format(r=ON_SITE_RADIUS_M, lat=lat, lon=lon)
    data = await _overpass_query(query_small, timeout_sec=20)

    if data and isinstance(data, dict):
        elements = data.get("elements") or []
        candidates = []
        for el in elements:
            tags = el.get("tags") or {}
            if not _fishable(tags):
                continue
            dist_km, inside = _min_dist_km_to_geometry(lat, lon, el)
            if dist_km == float("inf"):
                continue
            candidates.append((dist_km, inside, el, tags))

        on_site_cands = [c for c in candidates if c[1] or c[0] <= ON_SITE_RADIUS_KM]
        if on_site_cands:
            on_site_cands.sort(key=lambda c: (
                0 if c[1] else 1,
                0 if c[3].get("name") else 1,
                -_type_rank(c[3]),
                c[0],
            ))
            dist_km, inside, el, tags = on_site_cands[0]
            return _build_result(el, tags, dist_km, on_site=True, inside=inside)

    # --- Phase 2: nearest named (5km, center tags only) ---
    query_big = _QUERY_NEAREST.format(r=SEARCH_RADIUS_M, lat=lat, lon=lon)
    data = await _overpass_query(query_big, timeout_sec=20)

    if data and isinstance(data, dict):
        elements = data.get("elements") or []
        named = []
        for el in elements:
            tags = el.get("tags") or {}
            if not _fishable(tags) or not tags.get("name"):
                continue
            dist_km = _dist_to_center(lat, lon, el)
            if dist_km == float("inf"):
                continue
            named.append((dist_km, el, tags))

        if named:
            named.sort(key=lambda c: _type_rank(c[2]) - c[0], reverse=True)
            dist_km, el, tags = named[0]
            return _build_result(el, tags, dist_km, on_site=False, inside=False)

    return None


async def find_wide_waters(lat: float, lon: float, max_results: int = 8) -> list[dict]:
    """Search for major named water bodies within ~100 km using Nominatim.

    Returns a list of dicts with: name, type, distance_km, lat, lon, tags.
    Used when find_nearest_water() found nothing in 5 km.
    """
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    # ~1 degree ≈ 111 km
    delta = 0.9
    viewbox = f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}"
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=15)

    seen_names: set[str] = set()
    results: list[dict] = []

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for query_word in ("река", "озеро", "водохранилище", "пруд", "лиман"):
            params = {
                "q": query_word,
                "format": "json",
                "limit": 8,
                "viewbox": viewbox,
                "bounded": 1,
                "accept-language": "ru",
            }
            try:
                async with session.get(NOMINATIM_URL, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
            except Exception as exc:
                log.info("nominatim search '%s' failed: %s", query_word, exc)
                continue

            for item in data:
                display = item.get("display_name") or ""
                name_parts = display.split(",")
                name = name_parts[0].strip() if name_parts else ""
                if not name:
                    continue
                # Remove generic prefix like "озеро " from name for dedup
                name_key = name.lower()
                if name_key in seen_names:
                    continue
                seen_names.add(name_key)

                try:
                    elat = float(item["lat"])
                    elon = float(item["lon"])
                except (KeyError, ValueError):
                    continue

                dist_km = _haversine_km(lat, lon, elat, elon)
                if dist_km > 120:
                    continue

                # Determine type from the search word or OSM class
                osm_type = item.get("type") or ""
                wtype = {
                    "river": "река",
                    "water": query_word,
                    "reservoir": "водохранилище",
                    "lake": "озеро",
                    "pond": "пруд",
                }.get(osm_type, query_word)

                results.append({
                    "name": name,
                    "type": wtype,
                    "distance_km": round(dist_km, 1),
                    "lat": elat,
                    "lon": elon,
                    "tags": {},
                })

    # Sort by type importance then distance
    type_order = {"река": 5, "водохранилище": 4, "озеро": 3, "лиман": 2, "пруд": 1}
    results.sort(key=lambda r: (-type_order.get(r["type"], 0), r["distance_km"]))
    return results[:max_results]
