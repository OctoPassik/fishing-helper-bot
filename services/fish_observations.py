"""Объединение наблюдений рыб из нескольких источников (iNat + GBIF).

Назначение — один «фасад», который пытается обратиться к обоим источникам
параллельно, объединяет результат, дедуплицирует по латинскому названию,
и возвращает отсортированный по числу наблюдений список.

Сбой одного из источников не ломает ответ — возвращается частичный результат.
Если оба упали, возвращается пустой список (бот работает по общему списку).

Имеется простой LRU-кэш в памяти (ключ = округлённые координаты + радиус).
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from .gbif import fetch_gbif_fish
from .inaturalist import fetch_inat_fish

log = logging.getLogger(__name__)

# Простой in-memory LRU-кэш. Наблюдения не меняются быстро — OK хранить
# десятки минут между обновлениями от одного пользователя.
_CACHE: "OrderedDict[tuple, list[dict]]" = OrderedDict()
_CACHE_LIMIT = 256

def _cache_key(lat: float, lon: float, radius_km: float) -> tuple:
    # Округляем до ~1.1 км (0.01°) — хватает для кэширования соседних точек.
    return (round(lat, 2), round(lon, 2), int(radius_km))

def _cache_get(key: tuple) -> list[dict] | None:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None

def _cache_set(key: tuple, value: list[dict]) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)

def clear_cache() -> None:
    """Сбросить кэш (для тестов)."""
    _CACHE.clear()

async def _safe(coro, name: str) -> list[dict]:
    try:
        return await coro
    except Exception as exc:
        log.warning("observations source %s failed: %s", name, exc)
        return []

async def fetch_observations(
    lat: float,
    lon: float,
    radius_km: int = 25,
) -> list[dict]:
    """Fetch and merge fish observations from iNaturalist + GBIF.

    Returns a list of merged species records sorted by total count desc.
    Each record has:
        {
          "scientific": "Cyprinus carpio",
          "russian": "Карп" | None,
          "english": "European Carp" | None,
          "count": int,             # sum across all sources
          "photo_url": str | None,
          "wiki_url":  str | None,
          "sources": ["inaturalist", "gbif"],
        }

    Result is cached in-memory by (lat, lon, radius_km) rounded to ~1 km.
    """
    key = _cache_key(lat, lon, radius_km)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    inat_coro = fetch_inat_fish(lat, lon, radius_km=radius_km)
    # GBIF — используем вдвое больший радиус, т.к. данные там разрежённее.
    gbif_coro = fetch_gbif_fish(lat, lon, radius_km=max(radius_km * 2, 50))

    inat, gbif = await asyncio.gather(
        _safe(inat_coro, "inat"),
        _safe(gbif_coro, "gbif"),
    )

    merged: dict[str, dict] = {}
    for entry in list(inat) + list(gbif):
        sci = (entry.get("scientific") or "").strip()
        if not sci:
            continue
        key_sci = _normalize_latin_key(sci)
        existing = merged.get(key_sci)
        if existing:
            existing["count"] += entry.get("count", 0)
            if not existing.get("russian") and entry.get("russian"):
                existing["russian"] = entry["russian"]
            if not existing.get("english") and entry.get("english"):
                existing["english"] = entry["english"]
            if not existing.get("photo_url") and entry.get("photo_url"):
                existing["photo_url"] = entry["photo_url"]
            if not existing.get("wiki_url") and entry.get("wiki_url"):
                existing["wiki_url"] = entry["wiki_url"]
            src = entry.get("source")
            if src and src not in existing["sources"]:
                existing["sources"].append(src)
        else:
            merged[key_sci] = {
                "scientific": sci,
                "russian": entry.get("russian"),
                "english": entry.get("english"),
                "count": entry.get("count", 0),
                "photo_url": entry.get("photo_url"),
                "wiki_url": entry.get("wiki_url"),
                "sources": [entry.get("source")] if entry.get("source") else [],
            }

    result = sorted(merged.values(), key=lambda e: (-e["count"], e["scientific"]))
    _cache_set(key, result)
    return result

def _normalize_latin_key(name: str) -> str:
    """Use only 'Genus species' (lowercased) for dedup, ignoring author."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}".lower()
    return (parts[0] if parts else "").lower()
