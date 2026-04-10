"""iNaturalist client: наблюдения рыб по координатам.

Эндпоинт `species_counts` возвращает список видов с числом наблюдений
в радиусе от точки. С параметром `locale=ru` preferred_common_name
приходит на русском.

Документация: https://api.inaturalist.org/v1/docs/
"""
from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger(__name__)

INAT_SPECIES_COUNTS_URL = (
    "https://api.inaturalist.org/v1/observations/species_counts"
)

USER_AGENT = (
    "fishing-helper-bot/1.0 "
    "(+https://github.com/OctoPassik/fishing-helper-bot)"
)


async def fetch_inat_fish(
    lat: float,
    lon: float,
    radius_km: int = 25,
    per_page: int = 50,
    research_only: bool = False,
) -> list[dict]:
    """Fetch fish observations from iNaturalist in a given radius.

    Returns a list of dicts, one per species, sorted by observation count
    descending. Each dict has:

        {
          "scientific": "Cyprinus carpio",
          "russian": "Карп" | None,
          "english": "European Carp" | None,
          "count": 6,
          "photo_url": str | None,
          "wiki_url": str | None,
          "source": "inaturalist",
        }

    Raises `aiohttp.ClientError` if the API is unreachable.
    """
    params = {
        "lat": lat,
        "lng": lon,
        "radius": radius_km,
        "iconic_taxa": "Actinopterygii",
        "locale": "ru",
        "per_page": per_page,
    }
    if research_only:
        params["quality_grade"] = "research"

    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(INAT_SPECIES_COUNTS_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if not isinstance(data, dict):
        return []

    results: list[dict] = []
    for entry in data.get("results") or []:
        taxon = entry.get("taxon") or {}
        sci = taxon.get("name")
        if not sci:
            continue
        try:
            count = int(entry.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        photo = (taxon.get("default_photo") or {}).get("square_url")
        results.append(
            {
                "scientific": sci.strip(),
                "russian": _clean_name(taxon.get("preferred_common_name")),
                "english": _clean_name(taxon.get("english_common_name")),
                "count": count,
                "photo_url": photo,
                "wiki_url": taxon.get("wikipedia_url"),
                "source": "inaturalist",
            }
        )
    return results


def _clean_name(value) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    return s or None
