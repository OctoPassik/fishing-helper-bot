"""Продвинутый движок оценки клёва.

Учитывает:
- Текущее давление И тренд давления за 6 часов (главный фактор клёва)
- Текущее солунарное окно (major / minor) и близость к нему
- Близость к восходу / закату (зоря — ≈ +2 балла)
- Силу и направление ветра (сезонные бонусы)
- Тренд температуры за 12 часов
- Облачность, осадки
- Оценку температуры воды через 2-дневное скользящее среднее воздуха
- Фазу луны (лёгкий модификатор)

Возвращает *раздельные* оценки для мирной и хищной рыбы, потому что
у них разные оптимальные условия (яркое солнце — беда мирной, но хищник
чувствует себя нормально в тени; холодная вода — паралич мирной, а щука
активна).
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# -------------------------------------------------------------------- types ---

@dataclass
class BiteFactor:
    """Одна причина в оценке клёва."""
    text: str
    peaceful: int  # сдвиг для мирной
    predator: int  # сдвиг для хищника
    kind: str      # "good" / "bad" / "mixed" / "neutral"

    @property
    def abs_weight(self) -> int:
        return max(abs(self.peaceful), abs(self.predator))

@dataclass
class BiteReport:
    overall: int
    peaceful: int
    predator: int
    factors: list[BiteFactor]
    solunar_now: str | None        # "major"/"minor"/None
    solunar_next: tuple[str, int] | None  # (kind, minutes_until)
    sun_now: str | None            # "dawn"/"dusk"/None
    pressure_delta_6h: float       # мм рт.ст., знак важен
    temp_delta_12h: float          # °C
    water_temp_est: float | None   # °C, прикинуто
    kind_preference: str | None    # "мирная" / "хищная" / None (если скоры близки)

    @property
    def label(self) -> str:
        return overall_label(self.overall)

# ----------------------------------------------------------- time parsing ---

def parse_time_of_day(s: Any) -> int | None:
    """Преобразовать строку времени в минуты от полуночи.

    Принимает:
      "8:10 AM", "8:10 PM", "08:10", "20:10", "8:10"
      "2026-04-10T14:15" (ISO)
    """
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None

    # ISO format 2026-04-10T14:15[:00]
    if "T" in raw:
        try:
            # Обрежем смещение часового пояса, если есть
            main = raw.split("T", 1)[1]
            for sep in ("+", "-", "Z"):
                # только в time-части, не в дате
                idx = main.find(sep)
                if idx > 0:
                    main = main[:idx]
                    break
            parts = main.split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            if 0 <= hh < 24 and 0 <= mm < 60:
                return hh * 60 + mm
        except (ValueError, IndexError):
            return None
        return None

    upper = raw.upper().replace(" ", "")
    ampm = None
    if upper.endswith("AM"):
        ampm = "AM"
        upper = upper[:-2]
    elif upper.endswith("PM"):
        ampm = "PM"
        upper = upper[:-2]

    try:
        parts = upper.split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None

    if ampm == "PM" and hh < 12:
        hh += 12
    elif ampm == "AM" and hh == 12:
        hh = 0

    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return hh * 60 + mm

def get_current_local_minutes(weather: dict) -> int | None:
    """Current local time (minutes from midnight) as reported by Open-Meteo."""
    if not weather:
        return None
    current = weather.get("current") or {}
    return parse_time_of_day(current.get("time"))

# ----------------------------------------------------------- pressure ---

def _hpa_to_mmhg(hpa: float) -> float:
    return hpa * 0.75006

def _hourly_window(
    weather: dict, field: str, hours_back: int
) -> list[float]:
    """Return the values of an hourly field for the last `hours_back+1` hours.

    Uses `hourly.time` to locate the index of `current.time`.
    Returns an empty list if data is missing.
    """
    hourly = (weather or {}).get("hourly") or {}
    times: list[str] = hourly.get("time") or []
    values: list[Any] = hourly.get(field) or []
    if not times or not values or len(times) != len(values):
        return []
    current_time = ((weather or {}).get("current") or {}).get("time")
    if not current_time:
        return []
    try:
        idx = times.index(current_time)
    except ValueError:
        # Fallback — ближайшая точка по часу
        idx = -1
        for i, t in enumerate(times):
            if isinstance(t, str) and t.startswith(current_time[:13]):
                idx = i
                break
        if idx == -1:
            return []
    start = max(0, idx - hours_back)
    window = values[start : idx + 1]
    return [float(v) for v in window if v is not None]

def _pressure_trend_mmhg(weather: dict) -> tuple[float | None, float | None]:
    """(delta over 6h in mmHg, stddev in mmHg), or (None, None) if no data."""
    window_hpa = _hourly_window(weather, "surface_pressure", hours_back=6)
    if len(window_hpa) < 2:
        return None, None
    window = [_hpa_to_mmhg(p) for p in window_hpa]
    delta = window[-1] - window[0]
    mean = sum(window) / len(window)
    var = sum((p - mean) ** 2 for p in window) / len(window)
    return delta, math.sqrt(var)

def _temperature_trend(weather: dict, hours: int = 12) -> float:
    window = _hourly_window(weather, "temperature_2m", hours_back=hours)
    if len(window) < 2:
        return 0.0
    return window[-1] - window[0]

def _water_temp_estimate(weather: dict) -> float | None:
    """Грубая оценка температуры воды: среднее значение воздуха за ~48 часов.

    Вода меняется медленнее, чем воздух, так что скользящее среднее
    заметно ближе к реальной температуре воды, чем мгновенное значение.
    """
    hourly = (weather or {}).get("hourly") or {}
    values = hourly.get("temperature_2m") or []
    valid = [float(v) for v in values if v is not None]
    if len(valid) < 12:
        current_temp = ((weather or {}).get("current") or {}).get("temperature_2m")
        if current_temp is not None:
            return float(current_temp)
        return None
    avg = sum(valid) / len(valid)
    return avg

# ----------------------------------------------------------- solunar ---

def _solunar_current_window(
    solunar: dict | None, now_minutes: int
) -> str | None:
    """Если сейчас внутри major/minor окна — вернуть его тип."""
    if not solunar or now_minutes is None:
        return None
    for prefix in ("major", "minor"):
        for n in (1, 2):
            start = parse_time_of_day(solunar.get(f"{prefix}{n}Start"))
            stop = parse_time_of_day(solunar.get(f"{prefix}{n}Stop"))
            if start is None or stop is None:
                continue
            if stop < start:
                # окно пересекает полночь
                if now_minutes >= start or now_minutes <= stop:
                    return prefix
            elif start <= now_minutes <= stop:
                return prefix
    return None

def _solunar_next_window(
    solunar: dict | None, now_minutes: int, horizon_min: int = 120
) -> tuple[str, int] | None:
    """Если до major/minor окна меньше horizon_min — вернуть (тип, мин до начала)."""
    if not solunar or now_minutes is None:
        return None
    best: tuple[str, int] | None = None
    for prefix in ("major", "minor"):
        for n in (1, 2):
            start = parse_time_of_day(solunar.get(f"{prefix}{n}Start"))
            if start is None:
                continue
            delta = start - now_minutes
            if delta < 0:
                delta += 24 * 60
            if delta == 0:
                continue  # это уже "сейчас"
            if delta <= horizon_min:
                if best is None or delta < best[1]:
                    best = (prefix, delta)
    return best

# ----------------------------------------------------------- sun ---

def _minutes_from_iso_time(iso_str: str | None) -> int | None:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        if "T" in iso_str:
            return parse_time_of_day(iso_str)
        return parse_time_of_day(iso_str)
    except Exception:
        return None

def _sun_proximity(
    weather: dict, now_minutes: int, window_min: int = 75
) -> str | None:
    """Если сейчас внутри ±window_min от sunrise — 'dawn'; от sunset — 'dusk'."""
    if now_minutes is None:
        return None
    daily = (weather or {}).get("daily") or {}
    sunrises = daily.get("sunrise") or []
    sunsets = daily.get("sunset") or []
    sunrise_min = _minutes_from_iso_time(sunrises[0] if sunrises else None)
    sunset_min = _minutes_from_iso_time(sunsets[0] if sunsets else None)
    if sunrise_min is not None and abs(now_minutes - sunrise_min) <= window_min:
        return "dawn"
    if sunset_min is not None and abs(now_minutes - sunset_min) <= window_min:
        return "dusk"
    return None

# ----------------------------------------------------------- wind dir ---

def _wind_direction_bonus(
    degrees: Any, month: int, air_temp: float | None
) -> tuple[int, int, str]:
    """Return (peaceful_delta, predator_delta, description) based on wind dir."""
    if degrees is None:
        return 0, 0, ""
    try:
        d = float(degrees) % 360
    except (TypeError, ValueError):
        return 0, 0, ""

    # Юг/ЮЗ/З (135–270) — классический «рыбацкий» ветер
    if 135 <= d <= 270:
        return 1, 1, "южный/западный ветер — «рыбацкий»"

    # Север/СВ/СЗ (315-360, 0-45) — холодный
    if d >= 315 or d <= 45:
        cold_month = month in (10, 11, 12, 1, 2, 3)
        if cold_month or (air_temp is not None and air_temp < 10):
            return -1, -1, "северный ветер — холодный, не рыбацкий"
        return 0, 0, ""  # летний северный — нейтрально

    # Восточный
    return 0, 0, ""

# ----------------------------------------------------------- moon ---

def _moon_modifier(solunar: dict | None) -> tuple[int, int, str] | None:
    if not solunar:
        return None
    illum = solunar.get("moonIllumination")
    try:
        illum_f = float(illum) if illum is not None else None
    except (TypeError, ValueError):
        illum_f = None
    phase = (solunar.get("moonPhase") or "").strip().lower()

    if illum_f is not None:
        if illum_f >= 96 or illum_f <= 4:
            return -1, 0, "полнолуние/новолуние — клёв нестабилен"
        if 45 <= illum_f <= 55:
            return 1, 1, "четверть луны — часто хороший клёв"

    if "full" in phase:
        return -1, 0, "полнолуние — клёв нестабилен"
    if "new" in phase and "moon" in phase:
        return -1, 0, "новолуние — клёв нестабилен"
    return None

# ----------------------------------------------------------- label ---

def overall_label(score: int) -> str:
    if score >= 9:
        return "🟢 отличный"
    if score >= 7:
        return "🟢 хороший"
    if score >= 5:
        return "🟡 средний"
    if score >= 3:
        return "🟠 слабый"
    return "🔴 плохой"

# ----------------------------------------------------------- main ---

def compute_bite(
    *,
    weather: dict,
    solunar: dict | None,
    water: dict | None,
    today: _dt.date,
    now_minutes: int | None = None,
) -> BiteReport:
    """Compute a rich bite rating for the given conditions."""
    if now_minutes is None:
        now_minutes = get_current_local_minutes(weather)
        if now_minutes is None:
            now_minutes = 12 * 60  # noon fallback

    current = (weather or {}).get("current") or {}
    peaceful = 5
    predator = 5
    factors: list[BiteFactor] = []

    def add(
        text: str, peaceful_d: int, predator_d: int, kind: str
    ) -> None:
        nonlocal peaceful, predator
        peaceful += peaceful_d
        predator += predator_d
        factors.append(
            BiteFactor(text=text, peaceful=peaceful_d, predator=predator_d, kind=kind)
        )

    # ---------- 1. Тренд давления за 6 часов (главный фактор) ----------
    pressure_delta, pressure_std = _pressure_trend_mmhg(weather)
    if pressure_delta is None:
        # нет hourly данных — используем мгновенное значение
        current_p = current.get("surface_pressure_mmhg")
        if current_p is not None:
            if 748 <= current_p <= 762:
                add(f"давление в норме ({current_p:.0f} мм рт.ст.)", +2, +2, "good")
            elif 745 <= current_p <= 765:
                add(f"давление {current_p:.0f} мм рт.ст.", +1, +1, "neutral")
            else:
                add(f"давление {current_p:.0f} мм рт.ст. — аномально", -2, -2, "bad")
    else:
        if abs(pressure_delta) <= 1.0:
            add(
                f"давление стабильное ({pressure_delta:+.1f} мм/6ч)",
                +3, +3, "good",
            )
        elif -4.0 <= pressure_delta <= -1.0:
            # Плавное падение — классический жор перед непогодой
            add(
                f"давление плавно падает ({pressure_delta:+.1f} мм/6ч) — жор перед непогодой",
                +3, +2, "good",
            )
        elif 1.0 < pressure_delta <= 3.0:
            add(
                f"давление слабо растёт ({pressure_delta:+.1f} мм/6ч)",
                0, 0, "neutral",
            )
        elif pressure_delta < -4.0:
            add(
                f"давление резко падает ({pressure_delta:+.1f} мм/6ч) — рыба в стрессе",
                -3, -2, "bad",
            )
        else:  # pressure_delta > 3.0
            add(
                f"давление растёт ({pressure_delta:+.1f} мм/6ч) — рыба после шторма",
                -2, -1, "bad",
            )

    # ---------- 2. Текущее солунарное окно ----------
    solunar_now = _solunar_current_window(solunar, now_minutes)
    if solunar_now == "major":
        add("🔥 сейчас major-пик солунара", +3, +3, "good")
    elif solunar_now == "minor":
        add("✨ сейчас minor-пик солунара", +2, +2, "good")

    solunar_next = None
    if not solunar_now:
        solunar_next = _solunar_next_window(solunar, now_minutes, horizon_min=90)
        if solunar_next:
            kind, mins = solunar_next
            if mins <= 30:
                label = "major" if kind == "major" else "minor"
                add(
                    f"🔥 до {label}-пика {mins} мин — сейчас разогрев",
                    +2, +2, "good",
                )
            else:
                label = "major" if kind == "major" else "minor"
                add(
                    f"до {label}-пика {mins} мин",
                    +1, +1, "neutral",
                )

    # ---------- 3. Заря (близость к восходу/закату) ----------
    sun_now = _sun_proximity(weather, now_minutes)
    if sun_now == "dawn":
        add("🌅 сейчас утренняя зоря — лучший час суток", +2, +2, "good")
    elif sun_now == "dusk":
        add("🌇 сейчас вечерняя зоря — лучший час суток", +2, +2, "good")

    # ---------- 4. Облачность ----------
    clouds = current.get("cloud_cover")
    if clouds is not None:
        try:
            cl = float(clouds)
            if 30 <= cl <= 80:
                add("переменная облачность", +1, +1, "good")
            elif cl < 15:
                # Яркое солнце сильно бьёт по мирной рыбе (уходит на глубину).
                # Хищнику чуть проще — есть тень от коряг и берегового кустарника.
                if sun_now is None:
                    add(
                        f"яркое солнце ({cl:.0f}%) — мирная прячется",
                        -2, 0, "mixed",
                    )
            elif cl > 95:
                add("сплошная облачность", 0, 0, "neutral")
        except (TypeError, ValueError):
            pass

    # ---------- 5. Осадки ----------
    precip = current.get("precipitation")
    try:
        precip_f = float(precip) if precip is not None else 0.0
    except (TypeError, ValueError):
        precip_f = 0.0
    if precip_f > 5:
        add(f"ливень {precip_f:.1f} мм — ловить тяжело", -3, -2, "bad")
    elif precip_f > 1.5:
        add(f"дождь {precip_f:.1f} мм", -1, 0, "mixed")
    elif 0.1 < precip_f <= 1.5:
        add(f"лёгкий дождь {precip_f:.1f} мм — не мешает", 0, +1, "good")

    # ---------- 6. Ветер (сила) ----------
    wind = current.get("wind_speed_10m")
    try:
        wind_f = float(wind) if wind is not None else None
    except (TypeError, ValueError):
        wind_f = None
    if wind_f is not None and wind_f >= 0:
        if wind_f < 1:
            add(f"штиль ({wind_f:.1f} м/с) — рыба осторожна", -1, -1, "bad")
        elif wind_f <= 5:
            add(f"ветер {wind_f:.1f} м/с — идеальная рябь", +2, +1, "good")
        elif wind_f <= 8:
            add(f"ветер {wind_f:.1f} м/с", 0, 0, "neutral")
        else:
            add(f"сильный ветер {wind_f:.1f} м/с — сложно", -2, -1, "bad")

    # ---------- 7. Направление ветра (сезонно) ----------
    air_temp = current.get("temperature_2m")
    try:
        air_temp_f = float(air_temp) if air_temp is not None else None
    except (TypeError, ValueError):
        air_temp_f = None
    p_dir, d_dir, desc_dir = _wind_direction_bonus(
        current.get("wind_direction_10m"), today.month, air_temp_f
    )
    if desc_dir:
        add(desc_dir, p_dir, d_dir, "good" if p_dir > 0 else "bad")

    # ---------- 8. Тренд температуры за 12 ч ----------
    temp_delta = _temperature_trend(weather, hours=12)
    if temp_delta < -4:
        add(
            f"резкое похолодание ({temp_delta:+.0f}°C за 12ч) — мирная вялая",
            -2, 0, "mixed",
        )
    elif temp_delta < -2:
        add(f"похолодало ({temp_delta:+.0f}°C за 12ч)", -1, 0, "mixed")
    elif temp_delta > 4:
        add(
            f"резкое потепление ({temp_delta:+.0f}°C за 12ч) — рыба оживилась",
            +2, +1, "good",
        )

    # ---------- 9. Температура воды ----------
    water_temp = _water_temp_estimate(weather)
    if water_temp is not None:
        if water_temp > 32:
            add(
                f"вода ≈{water_temp:.0f}°C — пекло, мирная в стрессе",
                -3, -1, "mixed",
            )
        elif water_temp > 28:
            add(
                f"вода ≈{water_temp:.0f}°C — жара, мирная на глубине",
                -2, 0, "mixed",
            )
        elif water_temp < 5:
            add(
                f"вода ≈{water_temp:.0f}°C — холодно, мирная почти не клюёт",
                -3, 0, "mixed",
            )
        elif 14 <= water_temp <= 22:
            add(
                f"вода ≈{water_temp:.0f}°C — идеальный диапазон",
                +1, +1, "good",
            )

    # ---------- 10. Фаза луны ----------
    moon_mod = _moon_modifier(solunar)
    if moon_mod is not None:
        p, d, text = moon_mod
        add(text, p, d, "good" if p > 0 else "bad")

    # --- Clamp ---
    peaceful_c = max(0, min(10, peaceful))
    predator_c = max(0, min(10, predator))
    overall = round((peaceful_c + predator_c) / 2)

    # --- Предпочтение по типу рыбы ---
    kind_pref: str | None = None
    if peaceful_c >= predator_c + 2:
        kind_pref = "мирная"
    elif predator_c >= peaceful_c + 2:
        kind_pref = "хищная"

    return BiteReport(
        overall=overall,
        peaceful=peaceful_c,
        predator=predator_c,
        factors=factors,
        solunar_now=solunar_now,
        solunar_next=solunar_next,
        sun_now=sun_now,
        pressure_delta_6h=pressure_delta,
        temp_delta_12h=temp_delta,
        water_temp_est=water_temp,
        kind_preference=kind_pref,
    )
