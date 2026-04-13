"""Оценка клёва + сборка русскоязычного отчёта для пользователя."""
from __future__ import annotations

import datetime as _dt

from .bite import (
    BiteReport,
    compute_bite,
    get_current_local_minutes,
    overall_label,
)
from .fish_db import Fish, FISH_DB, recommend_fish, resolve_latin
from .water_fish_map import lookup_water_fish
from .solunar import moon_phase_ru
from .weather import wind_direction_ru

MONTH_RU_LOC = {
    1: "январе",
    2: "феврале",
    3: "марте",
    4: "апреле",
    5: "мае",
    6: "июне",
    7: "июле",
    8: "августе",
    9: "сентябре",
    10: "октябре",
    11: "ноябре",
    12: "декабре",
}

# Максимальная длина сообщения Telegram — 4096 символов. Держим запас.
TELEGRAM_MAX_LEN = 4000

def md_escape(text: str) -> str:
    """Escape user-generated text for Telegram legacy Markdown.

    Only four characters have markup meaning in legacy Markdown: * _ ` [
    We replace them with unicode look-alikes so visible output is preserved
    without breaking the parser. This is safer than backslash escaping,
    which legacy Markdown does not uniformly support.
    """
    if not text:
        return ""
    replacements = {
        "*": "∗",   # U+2217 asterisk operator
        "_": "‗",   # U+2017 double low line
        "`": "ʻ",   # U+02BB modifier letter turned comma
        "[": "⟦",   # U+27E6 mathematical left white square bracket
        "]": "⟧",   # U+27E7
    }
    for ch, repl in replacements.items():
        text = text.replace(ch, repl)
    return text

def smart_truncate(report: str, max_len: int = TELEGRAM_MAX_LEN) -> str:
    """Truncate a Markdown report without cutting inside an unclosed tag.

    Trims at the last newline before the limit and appends an ellipsis.
    The ellipsis line is never inside a markdown region because each logical
    section of the report is separated by a blank line.
    """
    if len(report) <= max_len:
        return report
    cut = report[: max_len - 6]
    last_nl = cut.rfind("\n\n")
    if last_nl == -1:
        last_nl = cut.rfind("\n")
    if last_nl > 0:
        cut = cut[:last_nl]
    # Если в обрезке осталось нечётное число `*` — добавим закрывающий,
    # чтобы Telegram не ломался.
    if cut.count("*") % 2 == 1:
        cut += "*"
    return cut + "\n\n…"

# --------------------------------------------------------------------- bite --

def _safe_float(v) -> float | None:
    """Convert any value to float, return None if impossible or NaN."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check
        return None
    return f

def bite_rating(current: dict) -> tuple[int, list[str]]:
    """Legacy-обёртка. Новый код использует compute_bite() напрямую."""
    fake_weather = {"current": current or {}, "hourly": {}, "daily": {}}
    report = compute_bite(
        weather=fake_weather,
        solunar=None,
        water=None,
        today=_dt.date.today(),
        now_minutes=12 * 60,
    )
    return report.overall, [_factor_line(f) for f in report.factors]

def bite_label(score: int) -> str:
    return overall_label(score)

def _factor_line(factor) -> str:
    icon = {"good": "✅", "bad": "⚠️", "mixed": "🟠"}.get(factor.kind, "🟡")
    return f"{icon} {factor.text}"

# ------------------------------------------------------ beginner explainers --

# Короткий глоссарий снастей. Показывается один раз в конце отчёта, чтобы
# новичок понимал слова «поплавок», «донка», «спиннинг».
_GEAR_GLOSSARY = (
    "• *Поплавок* — обычная удочка с поплавком на леске. Самая простая снасть, "
    "подходит для карася, плотвы, окуня.",
    "• *Донка / фидер* — удочка без поплавка. На конце лески грузик и крючок с "
    "наживкой, лежат на дне. Ловит крупную мирную рыбу: сазан, лещ, карп.",
    "• *Спиннинг* — палка с катушкой. На крючке не наживка, а *приманка* "
    "(блесна, воблер, силиконка), которую ты забрасываешь и тянешь. Ловит хищника: "
    "щуку, судака, окуня.",
)

_MAX_WEATHER_NOTES = 4  # лимит, чтобы отчёт вмещался в 4000 символов

def _format_weather_explainer(
    current: dict, bite_obj: "BiteReport"
) -> list[str]:
    """Короткие объяснения «что эта погода значит для клёва» — простым языком.

    Возвращаем только топ-`_MAX_WEATHER_NOTES` наиболее важных замечаний,
    приоритизируя solunar/заря → давление → ветер → температура → облачность.
    """
    temp = _safe_float(current.get("temperature_2m"))
    wind = _safe_float(current.get("wind_speed_10m"))
    pressure = _safe_float(current.get("surface_pressure_mmhg"))
    clouds = _safe_float(current.get("cloud_cover"))
    precip = _safe_float(current.get("precipitation"))

    notes: list[str] = []

    # Priority 1: solunar (crucial right now)
    if bite_obj.solunar_now == "major":
        notes.append(
            "• 🔥 *Ты в major-пике solunar* — окно 1.5–2 ч, когда "
            "рыба клюёт в разы активнее. Не уходи, забрасывай!"
        )
    elif bite_obj.solunar_now == "minor":
        notes.append(
            "• ✨ *Ты в minor-пике solunar* — клёв заметно сильнее среднего."
        )
    elif bite_obj.solunar_next and bite_obj.solunar_next[1] <= 45:
        kind, mins = bite_obj.solunar_next
        label = "major" if kind == "major" else "minor"
        notes.append(
            f"• До *{label}-пика* {mins} мин — раскладывайся заранее, "
            "чтобы к пику быть уже на точке."
        )

    # Priority 2: zorya (dawn/dusk)
    if bite_obj.sun_now == "dawn":
        notes.append(
            "• 🌅 *Утренняя зоря* — лучший час суток. Рыба вышла "
            "кормиться после ночи. Активно кидай."
        )
    elif bite_obj.sun_now == "dusk":
        notes.append(
            "• 🌇 *Вечерняя зоря* — второй лучший час суток, "
            "особенно для хищника."
        )

    # Priority 3: pressure trend (huge factor)
    if bite_obj.pressure_delta_6h is not None:
        delta = bite_obj.pressure_delta_6h
        if abs(delta) <= 1.0 and pressure is not None:
            notes.append(
                f"• Давление *стабильное* ({pressure:.0f} мм). Рыба "
                "спокойна, хорошо ест, не в стрессе — это *главный* "
                "фактор клёва."
            )
        elif -4.0 <= delta <= -1.0:
            notes.append(
                f"• Давление *плавно падает* ({delta:+.1f} мм за 6ч). "
                "Скоро непогода — перед ней рыба жадно кушает, это *жор*. "
                "Лови прямо сейчас!"
            )
        elif delta < -4.0:
            notes.append(
                f"• Давление *резко падает* ({delta:+.1f} мм за 6ч). "
                "Шторм приближается — рыба в стрессе."
            )
        elif delta > 3.0:
            notes.append(
                f"• Давление *растёт* ({delta:+.1f} мм за 6ч). "
                "Непогода прошла, рыба будет вялой 1–2 дня."
            )

    # Priority 4: temperature context
    if temp is not None:
        if temp < 0:
            notes.append(
                "• Мороз. Рыба спит, клюёт только зимний хищник — и то медленно."
            )
        elif temp < 8:
            notes.append(
                "• Холодно. Мирная вялая, клюёт днём. Хищник активнее."
            )
        elif temp > 30:
            notes.append(
                "• Пекло. Днём рыба не кормится — только ночью или "
                "рано утром."
            )
        elif 18 <= temp <= 25 and clouds is not None and clouds < 15:
            notes.append(
                "• Тепло и солнечно. Рыба прячется в тень, ищи места "
                "под деревьями или у коряг."
            )

    # Priority 5: wind (if not already covered by tips elsewhere)
    if wind is not None and len(notes) < _MAX_WEATHER_NOTES:
        if wind < 1:
            notes.append(
                "• *Штиль* — рыба видит тебя на берегу. Кидай *далеко*, "
                "не подходи к краю."
            )
        elif 2 <= wind <= 5:
            notes.append(
                f"• Лёгкая рябь ({wind:.0f} м/с) — *идеально*. Рыба не "
                "видит тебя, вода насыщается кислородом."
            )
        elif wind > 8:
            notes.append(
                f"• *Сильный ветер* ({wind:.0f} м/с). Ищи подветренный "
                "берег и закрытые заливы."
            )

    # Precipitation
    if precip is not None and precip > 1.5 and len(notes) < _MAX_WEATHER_NOTES:
        notes.append(
            f"• Дождь {precip:.1f} мм. Лёгкий дождь оживляет клёв, "
            "но сильный ливень — прячься, особенно если молния."
        )

    return notes[:_MAX_WEATHER_NOTES]

def _format_bite_explainer(bite_obj: "BiteReport") -> list[str]:
    """Объяснение «как читать оценку клёва»."""
    score = bite_obj.overall
    if score >= 9:
        text = (
            "Условия — супер. Если сейчас не поймаешь — значит снасть "
            "неправильно собрана. Иди на воду *немедленно*."
        )
    elif score >= 7:
        text = (
            "Условия хорошие. При грамотном подходе вернёшься с уловом. "
            "Самое время учиться — ошибки простит."
        )
    elif score >= 5:
        text = (
            "Средне. Клёв будет, но не бешеный. Рыбу придётся поискать, "
            "чаще менять место и наживку."
        )
    elif score >= 3:
        text = (
            "Слабо. Мирная рыба почти спит. Имеет смысл попробовать "
            "хищника на спиннинг или подождать изменения погоды."
        )
    else:
        text = (
            "Плохо. Честно — лучше пересидеть сегодня дома или "
            "прийти очень рано/очень поздно. Клёва почти не будет."
        )
    return [text]

def _format_solunar_explainer() -> str:
    return (
        "_Major-пики — это окна когда луна в зените или надире; рыба "
        "в это время жадно кушает. Minor-пики — восход/заход луны, "
        "клёв чуть слабее. Работают по всему миру круглый год._"
    )

def _format_bite_block(bite: "BiteReport") -> list[str]:
    """Render the bite rating block with peaceful/predator split + factors."""
    lines: list[str] = []
    lines.append(f"📊 *Клёв: {bite.overall}/10 — {overall_label(bite.overall)}*")

    # Мирная/хищник
    def _kind_line(label: str, score: int, is_preferred: bool) -> str:
        mark = " ⬅️" if is_preferred else ""
        return f"  {label}: *{score}/10* — {overall_label(score)}{mark}"

    lines.append(
        _kind_line(
            "🐟 мирная",
            bite.peaceful,
            bite.kind_preference == "мирная",
        )
    )
    lines.append(
        _kind_line(
            "🦈 хищник",
            bite.predator,
            bite.kind_preference == "хищная",
        )
    )

    # Топ причин — отсортируем по влиянию (самые мощные сверху), максимум 6.
    top = sorted(
        bite.factors,
        key=lambda f: (-f.abs_weight, bite.factors.index(f)),
    )[:6]
    if top:
        lines.append("")
        lines.append("📈 *Почему такая оценка*")
        for f in top:
            lines.append(f"  {_factor_line(f)}")
    return lines

# ----------------------------------------------------------------- helpers ---

def _extract_hhmm(s: str | None) -> str:
    """Достать HH:MM из ISO-строки или 'H:MM AM/PM', вернуть как есть иначе."""
    if not s or not isinstance(s, str):
        return "—"
    try:
        if "T" in s:
            return s.split("T", 1)[1][:5]
        return s
    except Exception:
        return s

def _format_day_rating(rating) -> str | None:
    """Solunar.org возвращает dayRating 0..2 (poor/fair/good).

    Некоторые форки используют 0..4. Выводим словом, чтобы не было неверного
    знаменателя.
    """
    try:
        r = int(rating)
    except (TypeError, ValueError):
        return None
    if r <= 0:
        return "🔴 плохой"
    if r == 1:
        return "🟡 средний"
    if r == 2:
        return "🟢 хороший"
    if r == 3:
        return "🟢 очень хороший"
    return "🟢 отличный"

def _is_krasnodar_krai(lat: float, lon: float) -> bool:
    return 43.4 <= lat <= 46.8 and 36.6 <= lon <= 41.9

def _krasnodar_nerest_warning(today: _dt.date) -> str | None:
    """Вернуть предупреждение о нерестовом запрете, если сейчас действует."""
    m, d = today.month, today.day
    active: list[str] = []

    # Общий запрет: 1 марта — 31 мая (большинство водоёмов)
    if (m == 3) or (m == 4) or (m == 5):
        active.append(
            "• 1 марта — 31 мая: *общий нерестовый запрет*. Ловля разрешена "
            "только *с берега*, вне нерестовых участков, на 1 поплавочную или "
            "донную удочку с *1–2 крючками*. Спиннинг, сети, лодки — "
            "запрещены."
        )

    # Щука: 15 января — 28/29 февраля
    if (m == 1 and d >= 15) or (m == 2):
        active.append(
            "• 15 января — 28 февраля: запрет на *щуку* в водоёмах "
            "рыбохозяйственного значения Краснодарского края."
        )

    # Тарань/лещ: 15 марта — 30 апреля в Азове, Кубани ниже КВХ, лиманах
    if (m == 3 and d >= 15) or m == 4:
        active.append(
            "• 15 марта — 30 апреля: запрет на *тарань и леща* в Азовском море, "
            "реке Кубань ниже Краснодарского гидроузла и азовских лиманах."
        )

    # Кефаль: 1–30 апреля
    if m == 4:
        active.append(
            "• 1 апреля — 30 апреля: запрет на *кефаль* (сингиль, лобан, остронос)."
        )

    if not active:
        return None

    header = "⚠️ *Нерестовый запрет* в Краснодарском крае сейчас действует:"
    footer = (
        "Штрафы — от 2 000 ₽ за особь + возмещение ущерба. "
        "Проверяй актуальные правила перед выездом."
    )
    return "\n".join([header, *active, "", footer])

# -------------------------------------------------------- water formatting --

def _water_type_prepositional(water_type: str) -> str:
    """Склонение типа водоёма в предложном падеже: река → реке."""
    return {
        "река": "реке",
        "озеро": "озере",
        "пруд": "пруду",
        "водохранилище": "водохранилище",
        "лиман": "лимане",
        "канал": "канале",
        "ручей": "ручье",
        "старица": "старице",
        "водоём": "водоёме",
    }.get(water_type.lower(), water_type)

def _format_water_header(water: dict | None) -> list[str]:
    """Собирает заголовок про водоём — разный для on_site и nearest."""
    if not water:
        return [
            "🎣 *Место рыбалки*",
            "_Ближайший водоём в радиусе 5 км не найден._",
        ]

    name = water.get("name")
    wtype_raw = (water.get("type") or "водоём").lower()
    wtype = md_escape(wtype_raw.capitalize())
    on_site = bool(water.get("on_site"))
    inside = bool(water.get("inside"))
    dist_km = water.get("distance_km")

    if on_site:
        if name:
            wname = md_escape(str(name))
            if inside:
                head = f"🎯 *Ты на воде: {wtype} {wname}*"
            else:
                head = f"🎯 *Ты на месте: {wtype} {wname}*"
        else:
            if inside:
                head = f"🎯 *Ты на воде: {wtype} (без названия в OSM)*"
            else:
                head = f"🎯 *Ты на месте: {wtype} (без названия в OSM)*"
        result = [head]
        if isinstance(dist_km, (int, float)) and dist_km > 0.01 and not inside:
            result.append(f"_до воды ≈ {int(dist_km * 1000)} м_")
        return result

    # Nearest, не on_site
    if name:
        wname = md_escape(str(name))
        head = f"🎣 *Ближайший водоём: {wtype} {wname}*"
        if isinstance(dist_km, (int, float)):
            head += f" — {dist_km:.1f} км"
        return [
            head,
            "_Ближе 250 м воды нет — ищи подъезд к этому водоёму._",
        ]
    return [
        "🎣 *Место рыбалки*",
        "_Ближайший именованный водоём в радиусе 5 км не найден._",
    ]

# Полезные OSM-теги водоёмов, которые стоит показать рыбаку.
_OSM_EXTRA_LABELS = (
    ("depth", "Глубина"),
    ("maxdepth", "Макс. глубина"),
    ("ele", "Высота над уровнем моря"),
)

def _format_water_extras(water: dict | None) -> list[str]:
    """Дополнительные полезные факты о водоёме из OSM-тегов."""
    if not water:
        return []
    tags = water.get("tags") or {}
    if not tags:
        return []

    extras: list[str] = []

    for key, label in _OSM_EXTRA_LABELS:
        val = tags.get(key)
        if val:
            extras.append(f"• {label}: {md_escape(str(val))} м")

    if tags.get("salt") == "yes" or tags.get("water") == "salt":
        extras.append("• 🧂 Вода солёная/солоноватая — рыба морская/лиманная")
    if tags.get("intermittent") == "yes":
        extras.append("• 💧 Водоём пересыхающий — уровень нестабилен")
    if tags.get("seasonal") == "yes":
        extras.append("• 🍂 Сезонный водоём — уровень сильно падает летом")

    reservoir_type = tags.get("reservoir_type")
    if reservoir_type:
        extras.append(
            f"• Тип водохранилища: {md_escape(str(reservoir_type))}"
        )

    fish_tag = tags.get("fish") or tags.get("fishing")
    if fish_tag and fish_tag not in ("no", "yes"):
        extras.append(f"• Рыба (OSM): {md_escape(str(fish_tag))}")
    if tags.get("fishing") == "no":
        extras.append("• ⛔ В OSM помечено как *fishing=no* — ловля запрещена!")

    if extras:
        return ["🌊 *Про водоём*", *extras]
    return []

# ----------------------------------------------------------------- report ----

def _process_observations(
    observations: list[dict] | None,
) -> tuple[dict[str, int], list[tuple[str, int]]]:
    """Split external fish observations into known-local and unknown.

    Returns (local_counts, unknown_list) where:
      - local_counts: {Fish.name: total_count} — species resolved to FISH_DB
      - unknown_list: [(label, count), ...] — species not in our DB, label is
                      best-available Russian name or Latin
    """
    local_counts: dict[str, int] = {}
    unknown: list[tuple[str, int]] = []
    if not observations:
        return local_counts, unknown

    for obs in observations:
        scientific = obs.get("scientific")
        count = int(obs.get("count") or 0)
        if count <= 0:
            continue
        fish = resolve_latin(scientific)
        if fish is not None:
            local_counts[fish.name] = local_counts.get(fish.name, 0) + count
        else:
            label = (
                obs.get("russian")
                or obs.get("english")
                or scientific
                or ""
            )
            if label:
                unknown.append((str(label), count))
    return local_counts, unknown

def _format_observations_section(
    local_counts: dict[str, int],
    unknown: list[tuple[str, int]],
    sources: set[str] | None = None,
) -> list[str]:
    """Build the 🔬 «Замечены здесь» section of the report."""
    if not local_counts and not unknown:
        return []

    source_label = "iNaturalist + GBIF"
    if sources:
        src_map = {"inaturalist": "iNaturalist", "gbif": "GBIF"}
        names = [src_map.get(s, s) for s in sources]
        if names:
            source_label = " + ".join(sorted(names))

    lines: list[str] = [f"🔬 *Замечены здесь* ({source_label})"]
    # Known local fish, sorted by count desc
    for name, count in sorted(local_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"• {md_escape(name)} — {count} набл.")

    # Unknown species — skip entirely (mostly aquarium escapees,
    # endangered species, and tiny non-game fish that confuse users)
    return lines

def build_report(
    *,
    lat: float,
    lon: float,
    weather: dict,
    solunar: dict | None,
    water: dict | None,
    today: _dt.date,
    observations: list[dict] | None = None,
    now_minutes: int | None = None,
) -> str:
    current = (weather or {}).get("current") or {}
    daily = (weather or {}).get("daily") or {}
    if now_minutes is None:
        now_minutes = get_current_local_minutes(weather)

    lines: list[str] = []

    # ----- заголовок -----
    lines.extend(_format_water_header(water))
    lines.append(f"📍 `{lat:.4f}, {lon:.4f}`")
    lines.append("")

    # ----- OSM-теги водоёма (глубина, соль, камыш и т.п.) -----
    extras = _format_water_extras(water)
    if extras:
        lines.extend(extras)
        lines.append("")

    # ----- погода -----
    temp = _safe_float(current.get("temperature_2m"))
    feels = _safe_float(current.get("apparent_temperature"))
    desc = current.get("weather_desc_ru", "")
    wind = _safe_float(current.get("wind_speed_10m"))
    gusts = _safe_float(current.get("wind_gusts_10m"))
    wind_dir = wind_direction_ru(current.get("wind_direction_10m"))
    pressure = _safe_float(current.get("surface_pressure_mmhg"))
    humidity = _safe_float(current.get("relative_humidity_2m"))
    clouds = _safe_float(current.get("cloud_cover"))
    precip = _safe_float(current.get("precipitation"))

    lines.append("🌤 *Погода сейчас*")
    if temp is not None:
        s = f"• Температура: {temp:+.0f}°C"
        if feels is not None:
            s += f" (ощущается {feels:+.0f}°C)"
        lines.append(s)
    if desc:
        s = f"• Небо: {desc}"
        if clouds is not None:
            s += f" ({clouds:.0f}% облачности)"
        lines.append(s)
    if wind is not None and wind >= 0:
        s = f"• Ветер: {wind:.1f} м/с, {wind_dir}"
        if gusts is not None and gusts > wind + 2:
            s += f" (порывы до {gusts:.0f})"
        lines.append(s)
    if pressure is not None and 500 < pressure < 900:
        lines.append(f"• Давление: {pressure:.0f} мм рт.ст.")
    if humidity is not None and 0 <= humidity <= 100:
        lines.append(f"• Влажность: {humidity:.0f}%")
    if precip is not None and precip > 0:
        lines.append(f"• Осадки: {precip:.1f} мм")

    try:
        tmax_list = daily.get("temperature_2m_max") or []
        tmin_list = daily.get("temperature_2m_min") or []
        tmax = _safe_float(tmax_list[0]) if tmax_list else None
        tmin = _safe_float(tmin_list[0]) if tmin_list else None
        if tmax is not None and tmin is not None:
            lines.append(f"• Сегодня: от {tmin:+.0f}°C до {tmax:+.0f}°C")
    except Exception:
        pass
    lines.append("")

    # Вычислим bite сразу — он нужен и для объяснений, и для оценки клёва
    bite = compute_bite(
        weather=weather,
        solunar=solunar,
        water=water,
        today=today,
        now_minutes=now_minutes,
    )

    # ----- «Что эта погода значит» — пояснения для новичка -----
    weather_notes = _format_weather_explainer(current, bite)
    if weather_notes:
        lines.append("👉 *Что это значит для клёва*")
        lines.extend(weather_notes)
        lines.append("")

    # ----- солнце и луна -----
    sunrise_list = daily.get("sunrise") or []
    sunset_list = daily.get("sunset") or []
    sunrise = _extract_hhmm(sunrise_list[0] if sunrise_list else None)
    sunset = _extract_hhmm(sunset_list[0] if sunset_list else None)

    have_solunar = bool(solunar)
    if have_solunar or (sunrise != "—" and sunset != "—"):
        lines.append("🌙 *Солнце и луна*")
        if sunrise != "—" and sunset != "—":
            lines.append(f"• Восход: {sunrise}  •  Закат: {sunset}")

        if have_solunar:
            moon = moon_phase_ru(solunar.get("moonPhase"))
            illum = _safe_float(solunar.get("moonIllumination"))
            s = f"• Луна: {moon}"
            if illum is not None:
                s += f" ({illum:.0f}%)"
            lines.append(s)

            majors = _collect_periods(solunar, prefix="major")
            if majors:
                lines.append(f"• 🔥 Пик клёва (major): {' / '.join(majors)}")
            minors = _collect_periods(solunar, prefix="minor")
            if minors:
                lines.append(f"• ✨ Малый пик (minor): {' / '.join(minors)}")

            day_rating_label = _format_day_rating(solunar.get("dayRating"))
            if day_rating_label:
                lines.append(
                    f"• Оценка дня по лунному календарю: {day_rating_label}"
                )
        # Короткое объяснение что такое major/minor пик (только если есть solunar)
        if have_solunar:
            lines.append(_format_solunar_explainer())
        lines.append("")

    # ----- оценка клёва -----
    lines.extend(_format_bite_block(bite))
    lines.append("")
    explainer = _format_bite_explainer(bite)
    lines.extend(f"_{line}_" for line in explainer)
    lines.append("")

    # ----- подготовка наблюдений (нужны для скоринга рыб) -----
    local_counts, unknown = _process_observations(observations)
    sources: set[str] = set()
    for obs in observations or []:
        for src in obs.get("sources") or ([obs.get("source")] if obs.get("source") else []):
            if src:
                sources.add(src)

    # ----- рыба по водоёму / сезону -----
    month = today.month
    raw_water_type = (water or {}).get("type")
    water_type = raw_water_type if raw_water_type and raw_water_type != "водоём" else None
    water_name = (water or {}).get("name")
    water_temp_guess = (
        bite.water_temp_est
        if bite.water_temp_est is not None
        else ((temp - 2.0) if temp is not None else 15.0)
    )

    # Попытаемся найти рыбу конкретно для этого водоёма
    water_fish_names = lookup_water_fish(water_name)
    use_water_specific = False

    if water_fish_names:
        # Собираем Fish-объекты из базы по именам, фильтруем по сезону
        fish_by_name = {f.name: f for f in FISH_DB}
        water_fishes_all = [fish_by_name[n] for n in water_fish_names if n in fish_by_name]
        # Фильтр по активному месяцу
        water_fishes_active = [f for f in water_fishes_all if month in f.active_months]
        if water_fishes_active:
            # Скоринг: пик сезона + температура + наблюдения + kind_preference
            scored: list[tuple[float, Fish]] = []
            for f in water_fishes_active:
                score = 5.0
                if month in f.peak_months:
                    score += 10.0
                tmin, tmax = f.water_temp_c
                if tmin <= water_temp_guess <= tmax:
                    score += 3.0
                if local_counts and f.name in local_counts:
                    score += 15.0 + min(float(local_counts[f.name]), 20.0)
                if bite.kind_preference and f.kind == bite.kind_preference:
                    score += 3.0
                scored.append((score, f))
            scored.sort(key=lambda x: -x[0])
            fishes = [f for _, f in scored[:5]]
            use_water_specific = True

    # Уровень 2: iNaturalist/GBIF наблюдения как основной источник
    use_observations = False
    if not use_water_specific and local_counts:
        # Есть реальные наблюдения рыб рядом — используем их как базу
        fish_by_name = {f.name: f for f in FISH_DB}
        obs_fishes = []
        for fname, count in sorted(local_counts.items(), key=lambda x: -x[1]):
            fish = fish_by_name.get(fname)
            if fish and month in fish.active_months:
                score = 15.0 + min(float(count), 20.0)
                if month in fish.peak_months:
                    score += 8.0
                if bite.kind_preference and fish.kind == bite.kind_preference:
                    score += 3.0
                obs_fishes.append((score, fish))
        if obs_fishes:
            obs_fishes.sort(key=lambda x: -x[0])
            fishes = [f for _, f in obs_fishes[:5]]
            use_observations = True

    # Уровень 3: сезонный fallback
    if not use_water_specific and not use_observations:
        fishes = recommend_fish(
            month,
            water_type,
            water_temp_guess,
            observed=local_counts or None,
            kind_preference=bite.kind_preference,
            max_items=4,
        )

    if use_water_specific:
        water_label = md_escape(water_name or "водоём")
        header = f"🐟 *Рыба в {water_label} в {MONTH_RU_LOC[month]}*"
        lines.append(header)
        lines.append("_📋 = из базы водоёма, 🔬 = подтверждено iNaturalist_")
    elif use_observations:
        header = f"🐟 *Рыба рядом в {MONTH_RU_LOC[month]}*"
        lines.append(header)
        lines.append("_🔬 по данным iNaturalist/GBIF_")
    else:
        header = f"🐟 *Что клюёт в {MONTH_RU_LOC[month]}* (по сезону)"
        lines.append(header)
    if fishes:
        for i, f in enumerate(fishes, 1):
            gear_str = ", ".join(f.gear)
            bait_str = ", ".join(f.baits[:4])
            peak_mark = "🔥 пик" if month in f.peak_months else "активна"
            # Пометка источника: 📋 = из базы водоёма, 🔬 = из iNaturalist
            if use_water_specific and f.name in local_counts:
                source = " 📋🔬"  # и в базе, и подтверждена iNat
            elif use_water_specific:
                source = " 📋"     # только в базе водоёма
            elif use_observations:
                source = " 🔬"     # только из iNaturalist
            else:
                source = ""
            lines.append(f"*{i}. {f.name}*{source} — {peak_mark} ({f.kind})")
            lines.append(f"   🎣 Снасть: {gear_str}")
            lines.append(f"   🪱 Наживка: {bait_str}")
            lines.append(f"   ⏰ Время: {f.best_time}")
            lines.append(f"   💡 {f.tip}")
            lines.append("")
    else:
        lines.append(
            "_Сейчас не самый активный месяц. Попробуй другой сезон._"
        )
        lines.append("")

    # ----- наблюдения iNaturalist + GBIF (после рыб) -----
    obs_lines = _format_observations_section(local_counts, unknown, sources)
    if obs_lines:
        lines.extend(obs_lines)
        lines.append("")

    # ----- нерестовый запрет Краснодарского края -----
    if _is_krasnodar_krai(lat, lon):
        nerest = _krasnodar_nerest_warning(today)
        if nerest:
            lines.append(nerest)
            lines.append("")

    # ----- советы новичку (только условно-специфичные) -----
    tips = _beginner_tips(fishes, current, bite)
    if tips:
        lines.append("👶 *Советы на сейчас*")
        lines.extend(tips)
        lines.append("")

    lines.append(
        "_Полный список снастей и базовых советов — в /help_"
    )

    return smart_truncate("\n".join(lines))

def _collect_periods(solunar: dict, prefix: str) -> list[str]:
    result: list[str] = []
    for n in (1, 2):
        start = solunar.get(f"{prefix}{n}Start")
        stop = solunar.get(f"{prefix}{n}Stop")
        if start and stop and isinstance(start, str) and isinstance(stop, str):
            result.append(f"{start}–{stop}")
    return result

def _beginner_tips(
    fishes: list[Fish], current: dict, bite_obj: "BiteReport | None" = None
) -> list[str]:
    """Только *условно-специфичные* советы для текущих условий.

    Статичные (приходить на зорю, не мусорить, проверить закон) вынесены
    в команду /help, чтобы не раздувать каждый отчёт до лимита Telegram.
    """
    tips: list[str] = []

    # Ситуативные snip'ы по solunar
    if bite_obj and bite_obj.solunar_now:
        tips.append(
            "• *Сейчас пик клёва* по solunar — не бросай снасти, лови прямо сейчас."
        )
    elif bite_obj and bite_obj.solunar_next:
        kind, mins = bite_obj.solunar_next
        tips.append(
            f"• До {kind}-пика {mins} мин — раскладывайся заранее, "
            "чтобы к пику быть готовым."
        )

    # Ветер
    wind = _safe_float(current.get("wind_speed_10m"))
    if wind is not None and wind > 6:
        tips.append(
            "• Ветер сильный — ищи *подветренный берег* (ветер тебе в спину), "
            "заливы, участки за кустами. Там вода спокойнее и заброс легче."
        )
    elif wind is not None and wind < 1:
        tips.append(
            "• *Штиль* — рыба видит тебя как на ладони. Одевайся тёмно, "
            "не подходи к краю берега, кидай *далеко*."
        )

    # Температура
    temp = _safe_float(current.get("temperature_2m"))
    if temp is not None:
        if temp < 5:
            tips.append(
                "• *Холодно*. Лови медленно у самого дна, маленькими "
                "приманками. Возьми термос — мёрзнущий рыбак быстро сдаётся."
            )
        elif temp > 28:
            tips.append(
                "• *Жарко*. Рыба ушла на глубину и в тень. Ищи тенистые "
                "места, мосты, коряги. Лови до 10 утра и после 19 часов."
            )

    # Критические сочетания
    has_peaceful = any(f.kind == "мирная" for f in fishes)
    has_predator = any(f.kind == "хищная" for f in fishes)
    if has_predator:
        tips.append(
            "• На *щуку* — обязательно металлический или флюорокарбоновый "
            "поводок 15 см. Без него щука перекусит леску."
        )

    return tips
