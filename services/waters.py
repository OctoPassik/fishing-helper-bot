"""Поиск водоёма через Overpass API (OpenStreetMap).

Двухуровневая логика:
1. ON_SITE — если геометрия водоёма находится ближе ON_SITE_RADIUS_KM
   (по умолчанию 250 м) или точка юзера внутри замкнутого контура — считаем,
   что он «прямо на месте». Берём даже безымянный пруд/старицу.
2. NEAREST — если ничего в On-Site-радиусе нет, ищем ближайший *именованный*
   водоём в пределах SEARCH_RADIUS_KM (5 км), как раньше.

Расстояние считается к ближайшему узлу геометрии (для way — все точки
береговой линии, для relation — все точки каждого члена). Для замкнутых
контуров (озёр) дополнительно делается point-in-polygon, чтобы «сидение в
лодке на середине озера» корректно опознавалось как on-site.
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

# Overpass API guidelines require a descriptive User-Agent.
USER_AGENT = "fishing-helper-bot/1.0 (+https://github.com/OctoPassik/fishing-helper-bot)"

# «Вы здесь» — если ближайшая точка водоёма ближе — считаем юзера на нём.
ON_SITE_RADIUS_KM = 0.25
# Радиус широкого поиска для fallback-а.
SEARCH_RADIUS_M = 5000

_QUERY_TMPL = """
[out:json][timeout:30];
(
  way(around:{r},{lat},{lon})["waterway"];
  way(around:{r},{lat},{lon})["natural"="water"];
  relation(around:{r},{lat},{lon})["natural"="water"];
  node(around:{r},{lat},{lon})["natural"="water"];
);
out geom 80;
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
    plat: float,
    plon: float,
    alat: float,
    alon: float,
    blat: float,
    blon: float,
) -> float:
    """Planar approximation of distance from P to segment AB in km.

    Uses equirectangular projection around the segment mid-latitude, which
    is accurate within a few % for distances under ~10 km. This matters for
    sparse OSM geometry (lake boundary with few nodes per long edge), where
    distance-to-nearest-node would wildly overestimate distance-to-shore.
    """
    mean_lat_rad = math.radians((alat + blat) * 0.5)
    kx = 111.320 * math.cos(mean_lat_rad)  # km per degree of longitude
    ky = 110.574                             # km per degree of latitude

    px = (plon - alon) * kx
    py = (plat - alat) * ky
    bx = (blon - alon) * kx
    by = (blat - alat) * ky

    seg_len2 = bx * bx + by * by
    if seg_len2 < 1e-12:
        return math.hypot(px, py)

    t = (px * bx + py * by) / seg_len2
    if t < 0:
        t = 0
    elif t > 1:
        t = 1

    dx = px - t * bx
    dy = py - t * by
    return math.hypot(dx, dy)


def _min_dist_km_to_ring(
    plat: float, plon: float, ring: list[dict]
) -> float:
    """Min distance from P to any edge of a polyline `ring` (list of {lat,lon})."""
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
        a = ring[i]
        b = ring[i + 1]
        if (
            a.get("lat") is None
            or a.get("lon") is None
            or b.get("lat") is None
            or b.get("lon") is None
        ):
            continue
        d = _point_to_segment_km(
            plat, plon, a["lat"], a["lon"], b["lat"], b["lon"]
        )
        if d < min_d:
            min_d = d
    return min_d


def _point_in_ring(lat: float, lon: float, ring: list[dict]) -> bool:
    """Planar ray-cast point-in-polygon (good enough for <10km areas).

    `ring` is a list of dicts with 'lat' / 'lon' keys. First and last may or
    may not coincide; we don't require that.
    """
    n = len(ring)
    if n < 3:
        return False
    x, y = lon, lat
    inside = False
    j = n - 1
    for i in range(n):
        xi = ring[i].get("lon")
        yi = ring[i].get("lat")
        xj = ring[j].get("lon")
        yj = ring[j].get("lat")
        if xi is None or yi is None or xj is None or yj is None:
            j = i
            continue
        denom = (yj - yi) or 1e-12
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / denom + xi):
            inside = not inside
        j = i
    return inside


def _is_closed(geometry: list[dict]) -> bool:
    """A way is a closed polygon if first/last coord match (within epsilon)."""
    if not geometry or len(geometry) < 3:
        return False
    first = geometry[0]
    last = geometry[-1]
    flat, flon = first.get("lat"), first.get("lon")
    llat, llon = last.get("lat"), last.get("lon")
    if flat is None or llat is None:
        return False
    return abs(flat - llat) < 1e-9 and abs(flon - llon) < 1e-9


def _min_dist_km_to_geometry(
    lat: float, lon: float, element: dict
) -> tuple[float, bool]:
    """Return (min_distance_km, is_inside).

    Computes minimum distance from (lat, lon) to any *segment* of the
    element's geometry (not just vertices). `is_inside` is True if the
    point is strictly inside a closed polygon of this element.
    """
    min_dist = float("inf")
    inside = False

    # node — есть прямо lat/lon в корне (без geometry)
    if "lat" in element and "lon" in element and "geometry" not in element:
        return _haversine_km(lat, lon, element["lat"], element["lon"]), False

    # way — geometry это список {lat, lon}
    geom = element.get("geometry")
    if geom:
        d = _min_dist_km_to_ring(lat, lon, geom)
        if d < min_dist:
            min_dist = d
        # замкнутый контур — проверим, не внутри ли мы
        if _is_closed(geom) and _point_in_ring(lat, lon, geom):
            inside = True
            min_dist = 0.0

    # relation — члены-way, каждый со своей geometry
    for member in element.get("members") or []:
        if member.get("type") != "way":
            continue
        mgeom = member.get("geometry")
        if not mgeom:
            continue
        d = _min_dist_km_to_ring(lat, lon, mgeom)
        if d < min_dist:
            min_dist = d
        # Если член — замкнутый outer ring и мы внутри — отметим.
        role = member.get("role") or "outer"
        if (
            role in ("outer", "")
            and _is_closed(mgeom)
            and _point_in_ring(lat, lon, mgeom)
        ):
            inside = True
            min_dist = 0.0

    if min_dist == float("inf"):
        return float("inf"), False
    return min_dist, inside


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
    """Higher = more significant for fishing."""
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
    """Skip things we definitely don't want (wastewater, basin, ditch tiny)."""
    if tags.get("water") in ("wastewater", "basin"):
        return False
    if tags.get("intermittent") == "yes" and not tags.get("name"):
        return False
    return True


def _build_result(
    element: dict,
    tags: dict,
    dist_km: float,
    on_site: bool,
    inside: bool,
) -> dict:
    return {
        "name": tags.get("name"),  # может быть None для on_site
        "type": _human_type(tags),
        "distance_km": round(dist_km, 3),
        "on_site": on_site,
        "inside": inside,  # True если юзер в контуре озера/лимана
        "element_type": element.get("type"),
        "tags": tags,
    }


# --------------------------------------------------------------- main ---

async def find_nearest_water(lat: float, lon: float) -> dict | None:
    """Find water body the user is on, or the nearest named one.

    Returns a dict with at least `name`, `type`, `distance_km`, `on_site`,
    `tags`. Name may be None if on_site and the water has no OSM name.
    Returns None if Overpass is unreachable or nothing relevant found.
    """
    query = _QUERY_TMPL.format(r=SEARCH_RADIUS_M, lat=lat, lon=lon)
    timeout = aiohttp.ClientTimeout(total=45)
    headers = {"User-Agent": USER_AGENT}

    data = None
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for url in OVERPASS_ENDPOINTS:
            try:
                async with session.post(url, data={"data": query}) as resp:
                    if resp.status != 200:
                        log.info("overpass %s: HTTP %s", url, resp.status)
                        continue
                    data = await resp.json()
                    break
            except Exception as exc:
                log.info("overpass %s failed: %s", url, exc)
                continue

    if not data or not isinstance(data, dict):
        return None

    elements = data.get("elements") or []

    # Посчитаем расстояние + флаг "внутри" для каждого элемента.
    candidates: list[tuple[float, bool, dict, dict]] = []
    for el in elements:
        tags = el.get("tags") or {}
        if not _fishable(tags):
            continue
        dist_km, inside = _min_dist_km_to_geometry(lat, lon, el)
        if dist_km == float("inf"):
            continue
        candidates.append((dist_km, inside, el, tags))

    if not candidates:
        return None

    # ------- Фаза 1: «ты на месте» -------
    on_site_cands = [
        c for c in candidates if c[1] or c[0] <= ON_SITE_RADIUS_KM
    ]
    if on_site_cands:
        # Предпочтение: внутри полигона → именованное → выше type_rank → ближе
        on_site_cands.sort(
            key=lambda c: (
                0 if c[1] else 1,                  # inside first
                0 if c[3].get("name") else 1,      # named first
                -_type_rank(c[3]),                 # significant type first
                c[0],                              # closer first
            )
        )
        dist_km, inside, el, tags = on_site_cands[0]
        return _build_result(el, tags, dist_km, on_site=True, inside=inside)

    # ------- Фаза 2: ближайший именованный -------
    named = [c for c in candidates if c[3].get("name")]
    if not named:
        return None

    def _score(c):
        dist_km, _inside, _el, tags = c
        return _type_rank(tags) - dist_km  # чем выше, тем лучше

    named.sort(key=_score, reverse=True)
    dist_km, inside, el, tags = named[0]
    return _build_result(el, tags, dist_km, on_site=False, inside=inside)
