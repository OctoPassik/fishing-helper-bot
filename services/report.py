"""Оценка клёва + сборка русскоязычного отчёта для пользователя."""
from __future__ import annotations

import datetime as _dt

from .fish_db import Fish, recommend_fish
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
    """Вернуть (score 0..10, список причин).

    Все значения ветра — в м/с (wind_speed_unit=ms в Open-Meteo).
    """
    score = 5
    notes: list[str] = []

    pressure = _safe_float(current.get("surface_pressure_mmhg"))
    if pressure is not None and 500 < pressure < 900:  # sanity
        if 748 <= pressure <= 762:
            score += 2
            notes.append(f"✅ давление в норме ({pressure:.0f} мм рт.ст.)")
        elif 745 <= pressure <= 765:
            score += 1
            notes.append(f"🟡 давление {pressure:.0f} мм рт.ст.")
        else:
            score -= 2
            notes.append(
                f"⚠️ давление {pressure:.0f} мм рт.ст. — рыба будет вялая"
            )

    wind = _safe_float(current.get("wind_speed_10m"))
    if wind is not None and wind >= 0:
        if wind < 1:
            score -= 1
            notes.append(f"🟡 штиль ({wind:.1f} м/с) — рыба осторожнее")
        elif wind <= 5:
            score += 2
            notes.append(f"✅ ветер {wind:.1f} м/с — идеальная рябь")
        elif wind <= 8:
            notes.append(f"🟡 ветер {wind:.1f} м/с — терпимо")
        else:
            score -= 2
            notes.append(f"⚠️ сильный ветер {wind:.1f} м/с — сложно ловить")

    clouds = _safe_float(current.get("cloud_cover"))
    if clouds is not None:
        if 30 <= clouds <= 80:
            score += 1
            notes.append("✅ переменная облачность — самое то")
        elif clouds > 95:
            notes.append("🟡 сплошная облачность")

    precip = _safe_float(current.get("precipitation"))
    if precip is not None and precip > 2:
        score -= 2
        notes.append(f"⚠️ осадки {precip:.1f} мм — неприятно ловить")

    temp = _safe_float(current.get("temperature_2m"))
    if temp is not None:
        if temp < 0:
            score -= 1
            notes.append("🟡 ниже нуля — клёв только у хищника")
        elif temp > 30:
            score -= 1
            notes.append("🟡 жара — рыба уйдёт на глубину")

    score = max(0, min(10, score))
    return score, notes


def bite_label(score: int) -> str:
    if score >= 8:
        return "🟢 отличный"
    if score >= 6:
        return "🟢 хороший"
    if score >= 4:
        return "🟡 средний"
    if score >= 2:
        return "🟠 слабый"
    return "🔴 плохой"


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


# ----------------------------------------------------------------- report ----

def build_report(
    *,
    lat: float,
    lon: float,
    weather: dict,
    solunar: dict | None,
    water: dict | None,
    today: _dt.date,
) -> str:
    current = (weather or {}).get("current") or {}
    daily = (weather or {}).get("daily") or {}

    lines: list[str] = []

    # ----- заголовок -----
    water_name = (water or {}).get("name")
    if water and water_name:
        wtype = (water.get("type") or "водоём").capitalize()
        wname = md_escape(str(water_name))
        wdist = water.get("distance_km")
        head = f"🎣 *{md_escape(wtype)} {wname}*"
        if isinstance(wdist, (int, float)):
            head += f" — {wdist:.1f} км от тебя"
        lines.append(head)
    else:
        lines.append("🎣 *Место рыбалки*")
        lines.append("_Ближайший именованный водоём в радиусе 5 км не найден._")
    lines.append(f"📍 `{lat:.4f}, {lon:.4f}`")
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
        lines.append("")

    # ----- оценка клёва -----
    score, notes = bite_rating(current)
    lines.append(f"📊 *Клёв: {score}/10 — {bite_label(score)}*")
    for n in notes:
        lines.append(f"  {n}")
    lines.append("")

    # ----- рыба по сезону -----
    month = today.month
    raw_water_type = (water or {}).get("type")
    # «водоём» — fallback-тип от Overpass, его не учитываем как фильтр habitat.
    water_type = raw_water_type if raw_water_type and raw_water_type != "водоём" else None
    water_temp_guess = (temp - 2.0) if temp is not None else 15.0
    fishes = recommend_fish(month, water_type, water_temp_guess, max_items=4)

    lines.append(f"🐟 *Что клюёт в {MONTH_RU_LOC[month]}*")
    if fishes:
        for i, f in enumerate(fishes, 1):
            gear_str = ", ".join(f.gear)
            bait_str = ", ".join(f.baits[:4])
            peak_mark = "🔥 пик сезона" if month in f.peak_months else "активна"
            lines.append(f"*{i}. {f.name}* — {peak_mark} ({f.kind})")
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

    # ----- нерестовый запрет Краснодарского края -----
    if _is_krasnodar_krai(lat, lon):
        nerest = _krasnodar_nerest_warning(today)
        if nerest:
            lines.append(nerest)
            lines.append("")

    # ----- советы новичку -----
    lines.append("👶 *Советы новичку*")
    lines.extend(_beginner_tips(fishes, current))

    return smart_truncate("\n".join(lines))


def _collect_periods(solunar: dict, prefix: str) -> list[str]:
    result: list[str] = []
    for n in (1, 2):
        start = solunar.get(f"{prefix}{n}Start")
        stop = solunar.get(f"{prefix}{n}Stop")
        if start and stop and isinstance(start, str) and isinstance(stop, str):
            result.append(f"{start}–{stop}")
    return result


def _beginner_tips(fishes: list[Fish], current: dict) -> list[str]:
    tips: list[str] = []
    has_predator = any(f.kind == "хищная" for f in fishes)
    has_peaceful = any(f.kind == "мирная" for f in fishes)

    if has_peaceful:
        tips.append(
            "• Для мирной рыбы (карась, плотва, лещ) — поплавочная удочка "
            "4–5 м, леска 0.16–0.20, крючок №10–14."
        )
    if has_predator:
        tips.append(
            "• Для хищника — лёгкий спиннинг 2.1–2.4 м, плетёнка 0.10–0.12, "
            "на щуку обязательно металлический поводок."
        )
    tips.append(
        "• Приходи на водоём за 30–40 минут до восхода или за 1 час до заката — "
        "это лучшие окна для клёва."
    )
    tips.append("• Прикармливай точку малыми порциями. Не шуми на берегу.")

    wind = _safe_float(current.get("wind_speed_10m"))
    if wind is not None and wind > 6:
        tips.append(
            "• Ветер сильный — ищи закрытые заливы и подветренный берег."
        )

    temp = _safe_float(current.get("temperature_2m"))
    if temp is not None:
        if temp < 5:
            tips.append(
                "• Холодно — рыба пассивна, лови медленно у дна. Оденься "
                "теплее, возьми термос."
            )
        elif temp > 28:
            tips.append(
                "• Жарко — рыба уходит на глубину и в тень. Лучший клёв "
                "рано утром и после заката."
            )

    precip = _safe_float(current.get("precipitation")) or 0.0
    if precip < 0.1 and (temp if temp is not None else 10) >= 5:
        tips.append("• Сухо — не забудь головной убор и воду. SPF-крем тоже.")

    tips.append("• Возьми подсак и зажим для крючка — пригодятся.")
    tips.append("• Мусор забирай с собой ♻️ — оставим водоёмы чистыми.")
    tips.append(
        "• Обязательно проверь актуальные правила рыболовства и нерестовые "
        "запреты в своём регионе перед выездом."
    )
    return tips
