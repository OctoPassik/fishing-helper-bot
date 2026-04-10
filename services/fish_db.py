"""База знаний о рыбах Краснодарского края / юга России.

Каждая запись содержит активные месяцы, пиковые месяцы, подходящие снасти,
наживки, оптимальный температурный диапазон воды, типы водоёмов, лучшее
время суток, короткий совет новичку и список латинских имён (для связки
с внешними API наблюдений — iNaturalist, GBIF и т.п.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class Fish:
    name: str
    kind: str  # "мирная" / "хищная"
    active_months: tuple[int, ...]
    peak_months: tuple[int, ...]
    gear: tuple[str, ...]
    baits: tuple[str, ...]
    water_temp_c: tuple[float, float]
    habitats: tuple[str, ...]
    best_time: str
    tip: str
    latin_names: tuple[str, ...] = ()


FISH_DB: tuple[Fish, ...] = (
    Fish(
        name="Карась",
        kind="мирная",
        active_months=(4, 5, 6, 7, 8, 9, 10),
        peak_months=(5, 6, 9),
        gear=("поплавок", "донка/фидер"),
        baits=("червь", "опарыш", "кукуруза", "перловка", "тесто"),
        water_temp_c=(10.0, 26.0),
        habitats=("пруд", "озеро", "старица", "лиман", "канал", "водоём"),
        best_time="утро и вечер",
        tip=(
            "Идеальная рыба для новичка. Поплавочка 4–5 м, леска 0.16, "
            "крючок №10–12, насадка — червь или кукуруза. Прикорми 1–2 "
            "горсти панировки с жареными семечками у камыша."
        ),
        latin_names=(
            "Carassius gibelio",
            "Carassius auratus",
            "Carassius carassius",
            "Carassius",
        ),
    ),
    Fish(
        name="Сазан (карп)",
        kind="мирная",
        active_months=(4, 5, 6, 7, 8, 9, 10),
        peak_months=(5, 6, 7, 9),
        gear=("донка/фидер",),
        baits=("кукуруза", "бойлы", "горох", "перловка", "червь"),
        water_temp_c=(14.0, 28.0),
        habitats=("река", "озеро", "водохранилище", "пруд", "лиман", "канал"),
        best_time="раннее утро и ночь",
        tip=(
            "Фидер с кормушкой 40–60 г. Прикормка — кукуруза + пелетс + "
            "магазинная карповая. Леска 0.25, поводок 0.20, крючок №6–8. "
            "Сазан любит тишину — не шуми на берегу."
        ),
        latin_names=(
            "Cyprinus carpio",
            "Cyprinus rubrofuscus",
            "Cyprinus",
        ),
    ),
    Fish(
        name="Плотва / тарань",
        kind="мирная",
        active_months=tuple(range(1, 13)),
        peak_months=(4, 5, 10),
        gear=("поплавок",),
        baits=("мотыль", "опарыш", "червь", "тесто"),
        water_temp_c=(4.0, 22.0),
        habitats=("река", "озеро", "водохранилище", "лиман", "пруд", "канал", "водоём"),
        best_time="утро",
        tip=(
            "Лёгкая поплавочка, крючок №14–16, поплавок 1–2 г. На юге "
            "тарань — массовая рыба, клюёт почти круглый год. Хороша для "
            "тренировки заброса и подсечки."
        ),
        latin_names=(
            "Rutilus rutilus",
            "Rutilus frisii",
            "Rutilus lacustris",
            "Rutilus heckelii",
            "Rutilus",
        ),
    ),
    Fish(
        name="Лещ / густера",
        kind="мирная",
        active_months=(4, 5, 6, 7, 8, 9, 10),
        peak_months=(5, 6, 9),
        gear=("донка/фидер", "поплавок"),
        baits=("червь", "опарыш", "кукуруза", "перловка", "мотыль"),
        water_temp_c=(10.0, 24.0),
        habitats=("река", "водохранилище", "озеро", "лиман", "канал"),
        best_time="вечер и ночь",
        tip=(
            "Лучше всего фидер на глубине 3–6 м. Прикормка — магазинная "
            "для леща с добавлением кукурузы. Крючок №10, поводок 0.14."
        ),
        latin_names=(
            "Abramis brama",
            "Abramis",
            "Blicca bjoerkna",
            "Blicca",
        ),
    ),
    Fish(
        name="Щука",
        kind="хищная",
        active_months=(1, 2, 3, 4, 9, 10, 11, 12),
        peak_months=(3, 4, 10, 11),
        gear=("спиннинг",),
        baits=("колебалка", "воблер", "джиг", "силикон", "живец"),
        water_temp_c=(4.0, 20.0),
        habitats=("река", "озеро", "водохранилище", "лиман", "канал", "старица", "пруд"),
        best_time="утро и вечер",
        tip=(
            "Спиннинг 2.1–2.4 м тест 7–28 г, плетёнка 0.12, *обязательно* "
            "металлический или флюорокарбоновый поводок. Рабочие приманки: "
            "колебалка 10–15 г, воблер-минноу 80–110 мм, джиг 8–14 г."
        ),
        latin_names=("Esox lucius", "Esox"),
    ),
    Fish(
        name="Судак",
        kind="хищная",
        active_months=(1, 2, 3, 4, 5, 9, 10, 11, 12),
        peak_months=(4, 5, 10),
        gear=("спиннинг", "донка/фидер"),
        baits=("джиг-силикон", "воблер", "живец", "тюлька"),
        water_temp_c=(6.0, 22.0),
        habitats=("река", "водохранилище", "лиман"),
        best_time="сумерки и ночь",
        tip=(
            "Джиг у дна 10–16 г, виброхвост 3–4 дюйма, проводка ступенькой "
            "(2–3 оборота + пауза 2 сек). Судак стоит на русловых бровках "
            "и в коряжниках."
        ),
        latin_names=(
            "Sander lucioperca",
            "Sander volgensis",
            "Stizostedion lucioperca",
            "Sander",
        ),
    ),
    Fish(
        name="Окунь",
        kind="хищная",
        active_months=tuple(range(1, 13)),
        peak_months=(4, 5, 9, 10),
        gear=("спиннинг", "поплавок"),
        baits=("микроджиг", "вертушка №1–3", "червь", "малёк"),
        water_temp_c=(4.0, 22.0),
        habitats=("река", "озеро", "водохранилище", "пруд", "канал", "лиман", "водоём"),
        best_time="день",
        tip=(
            "Новичку — лёгкий спиннинг с вертушкой №2 или микроджиг 2–4 г. "
            "Если не клюёт — перейди на поплавочку с червём, окунь почти "
            "всегда найдётся у камыша или коряг."
        ),
        latin_names=("Perca fluviatilis", "Perca"),
    ),
    Fish(
        name="Жерех",
        kind="хищная",
        active_months=(5, 6, 7, 8, 9, 10),
        peak_months=(6, 7, 8),
        gear=("спиннинг",),
        baits=("кастмастер", "пилькер", "воблер", "стример"),
        water_temp_c=(14.0, 26.0),
        habitats=("река", "канал"),
        best_time="день",
        tip=(
            "Ищи «бой» — всплески на перекатах и струях. Кидай кастмастер "
            "17–28 г далеко и быстро веди по поверхности или чуть глубже."
        ),
        latin_names=("Aspius aspius", "Leuciscus aspius", "Aspius"),
    ),
    Fish(
        name="Сом",
        kind="хищная",
        active_months=(5, 6, 7, 8, 9),
        peak_months=(6, 7, 8),
        gear=("донка/фидер", "спиннинг"),
        baits=("выползок пучком", "живец", "лягушка", "куриная печень"),
        water_temp_c=(18.0, 28.0),
        habitats=("река", "водохранилище", "лиман"),
        best_time="ночь",
        tip=(
            "Мощная донка: леска 0.40–0.50, крючок №1–3/0, груз 60–100 г. "
            "Лучшее время — тёплая летняя ночь 22:00–03:00 на ямах и "
            "выходах с них. Обязательно подсак или багор."
        ),
        latin_names=(
            "Silurus glanis",
            "Silurus",
            "Ictalurus punctatus",  # канальный сомик — из того же рода
        ),
    ),
    Fish(
        name="Толстолобик",
        kind="мирная",
        active_months=(5, 6, 7, 8, 9),
        peak_months=(6, 7, 8),
        gear=("донка/фидер",),
        baits=("технопланктон", "зелень", "камыш"),
        water_temp_c=(18.0, 28.0),
        habitats=("водохранилище", "пруд", "озеро", "лиман"),
        best_time="день",
        tip=(
            "Специальная снасть «убийца толстолобика» с технопланктоном. "
            "Для новичка сложновато, зато в краснодарских прудах и "
            "водохранилищах — очень результативно."
        ),
        latin_names=(
            "Hypophthalmichthys molitrix",
            "Hypophthalmichthys nobilis",
            "Hypophthalmichthys",
            "Aristichthys nobilis",
        ),
    ),
    Fish(
        name="Белый амур",
        kind="мирная",
        active_months=(5, 6, 7, 8, 9),
        peak_months=(6, 7, 8),
        gear=("донка/фидер", "поплавок"),
        baits=("огурец", "листья камыша", "кукуруза", "горох"),
        water_temp_c=(18.0, 28.0),
        habitats=("водохранилище", "пруд", "озеро", "канал"),
        best_time="утро",
        tip=(
            "Мощная донка: леска 0.30, крючок №4–6. Живая насадка — "
            "кусочек огурца или свежий лист камыша очень рабочи в жару."
        ),
        latin_names=(
            "Ctenopharyngodon idella",
            "Ctenopharyngodon",
        ),
    ),
    Fish(
        name="Голавль",
        kind="хищная",
        active_months=(4, 5, 6, 7, 8, 9, 10),
        peak_months=(5, 6, 7),
        gear=("спиннинг", "поплавок"),
        baits=("майский жук", "кузнечик", "воблер-кренк", "вишня", "черешня"),
        water_temp_c=(10.0, 24.0),
        habitats=("река", "канал"),
        best_time="день",
        tip=(
            "Ищи перекаты и участки под нависшими ветками. Маленький "
            "воблер-кренк 3–5 см или майский жук поверху — самое то."
        ),
        latin_names=(
            "Squalius cephalus",
            "Leuciscus cephalus",
            "Squalius",
            "Petroleuciscus aphipsi",  # эндемик реки Афипс
            "Petroleuciscus",
        ),
    ),
    Fish(
        name="Краснопёрка",
        kind="мирная",
        active_months=(4, 5, 6, 7, 8, 9, 10),
        peak_months=(5, 6, 7),
        gear=("поплавок",),
        baits=("опарыш", "червь", "тесто", "хлеб"),
        water_temp_c=(12.0, 26.0),
        habitats=("озеро", "пруд", "лиман", "старица", "канал", "водоём"),
        best_time="день",
        tip=(
            "Лови у поверхности на 0.5–1 м в заросшем камышом заливе. "
            "Крючок №14, поплавок 1 г. Отличная рыба для обучения детей."
        ),
        latin_names=(
            "Scardinius erythrophthalmus",
            "Scardinius",
        ),
    ),
    Fish(
        name="Линь",
        kind="мирная",
        active_months=(5, 6, 7, 8, 9),
        peak_months=(5, 6, 7),
        gear=("поплавок", "донка/фидер"),
        baits=("червь", "опарыш", "кукуруза", "перловка"),
        water_temp_c=(14.0, 24.0),
        habitats=("пруд", "озеро", "старица", "лиман", "водоём"),
        best_time="утро и вечер",
        tip=(
            "Ищи в тихих заросших заливах с илистым дном. Поплавок 1–2 г, "
            "крючок №8–10, червь или кукуруза. Линь клюёт медленно — "
            "не торопись с подсечкой."
        ),
        latin_names=("Tinca tinca", "Tinca"),
    ),
    Fish(
        name="Язь",
        kind="мирная",
        active_months=(3, 4, 5, 6, 7, 8, 9, 10),
        peak_months=(4, 5, 9),
        gear=("поплавок", "донка/фидер", "спиннинг"),
        baits=("червь", "горох", "опарыш", "воблер", "вертушка"),
        water_temp_c=(8.0, 22.0),
        habitats=("река", "водохранилище", "канал"),
        best_time="утро",
        tip=(
            "Язь любит струю и нависшие кусты. На поплавок — с проводкой "
            "по течению, на спиннинг — мелкие вертушки и воблеры-минноу 5–7 см."
        ),
        latin_names=("Leuciscus idus", "Leuciscus"),
    ),
    Fish(
        name="Чехонь",
        kind="мирная",
        active_months=(5, 6, 7, 8, 9, 10),
        peak_months=(6, 7, 8),
        gear=("поплавок", "спиннинг"),
        baits=("опарыш", "муха", "мелкий твистер", "малёк"),
        water_temp_c=(15.0, 26.0),
        habitats=("река", "водохранилище", "лиман"),
        best_time="день",
        tip=(
            "Чехонь стоит в толще воды на перекатах и русловых свалах. "
            "Лёгкий спиннинг с микроджигом 2–3 г или поплавок с опарышем "
            "в дальний заброс — рабочая тактика."
        ),
        latin_names=("Pelecus cultratus", "Pelecus"),
    ),
    Fish(
        name="Уклейка",
        kind="мирная",
        active_months=tuple(range(3, 12)),
        peak_months=(5, 6, 7, 8),
        gear=("поплавок",),
        baits=("опарыш", "тесто", "муха"),
        water_temp_c=(8.0, 26.0),
        habitats=(
            "река",
            "озеро",
            "водохранилище",
            "пруд",
            "канал",
            "лиман",
            "водоём",
        ),
        best_time="день",
        tip=(
            "Массовая верховодка, отлично подходит детям: поплавок 0.5–1 г, "
            "крючок №16–18, насадка на дно не нужна — ловим с 10–30 см. "
            "Пригодна как живец на крупного хищника."
        ),
        latin_names=("Alburnus alburnus", "Alburnus"),
    ),
    Fish(
        name="Бычок",
        kind="хищная",
        active_months=tuple(range(3, 12)),
        peak_months=(5, 6, 7, 8, 9, 10),
        gear=("поплавок", "донка/фидер"),
        baits=("червь", "креветка", "малёк", "мясо мидии"),
        water_temp_c=(10.0, 28.0),
        habitats=(
            "лиман",
            "река",
            "канал",
            "водохранилище",
            "водоём",
        ),
        best_time="день",
        tip=(
            "Массовая рыба азово-черноморского бассейна. Лови на донку или "
            "поплавок у дна, крючок №8, наживка — кусочек червя или креветка. "
            "В лиманах и Кубани ловится с весны до поздней осени."
        ),
        latin_names=(
            "Neogobius fluviatilis",
            "Neogobius melanostomus",
            "Neogobius",
            "Ponticola",
            "Ponticola kessleri",
            "Gobius",
        ),
    ),
)


# ---------------- Резолвер «латинское имя → локальная рыба» ---------------

# Строится из FISH_DB сразу после объявления. Ключ — latin в lowercase,
# значение — Fish. Допускаются как полные биномы ('Esox lucius'), так и
# только род ('Esox') — при отсутствии бинома пробуем сопоставить по роду.
_LATIN_TO_FISH: dict[str, Fish] = {}
for _fish in FISH_DB:
    for _lat in _fish.latin_names:
        key = _lat.strip().lower()
        if key:
            _LATIN_TO_FISH.setdefault(key, _fish)


def resolve_latin(scientific: str | None) -> Fish | None:
    """Map any scientific name (with optional author) to our local Fish.

    Tries the full 'Genus species' first, then just 'Genus' as fallback.
    Returns None if no match — caller should treat the species as
    "known to be in the area but not in our hardcoded DB".
    """
    if not scientific:
        return None
    parts = str(scientific).strip().split()
    if not parts:
        return None
    tries: list[str] = []
    if len(parts) >= 2:
        tries.append(f"{parts[0]} {parts[1]}".lower())
    tries.append(parts[0].lower())  # genus
    for key in tries:
        fish = _LATIN_TO_FISH.get(key)
        if fish is not None:
            return fish
    return None


# ----------------------------- Рекомендации ------------------------------


def recommend_fish(
    month: int,
    water_type: str | None,
    water_temp_guess: float,
    observed: dict[str, int] | None = None,
    max_items: int = 4,
) -> list[Fish]:
    """Return up to `max_items` fish likely to bite this month in given water.

    If `observed` is provided (mapping Fish.name → observation count from
    external APIs), matching species get a huge score boost so they dominate
    the top-N.
    """
    scored: list[tuple[float, Fish]] = []
    for fish in FISH_DB:
        if month not in fish.active_months:
            continue
        score = 3.0
        if month in fish.peak_months:
            score += 10.0
        if water_type and water_type in fish.habitats:
            score += 5.0
        tmin, tmax = fish.water_temp_c
        if tmin <= water_temp_guess <= tmax:
            score += 3.0
        if observed and fish.name in observed:
            # Жирный буст за реальные наблюдения поблизости.
            score += 15.0 + min(float(observed[fish.name]), 20.0)
        scored.append((score, fish))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:max_items]]


def all_species_for_month(month: int) -> Sequence[Fish]:
    return tuple(f for f in FISH_DB if month in f.active_months)
