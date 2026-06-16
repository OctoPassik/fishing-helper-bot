# 🎣 fishing-helper-bot

> **A Telegram bot that turns your location into a fishing forecast.**
> Send your geolocation → get the current bite rating, which fish are active, what tackle to use, and the best time to go. Built with `aiogram 3`, free data sources only (no API keys required).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3-009688?logo=python&logoColor=white)
[![Try the bot](https://img.shields.io/badge/Telegram-@fishocto__bot-26A5E4?logo=telegram&logoColor=white)](https://t.me/fishocto_bot)

🇬🇧 English summary below · 🇷🇺 [Полная версия на русском](#-русская-версия)

---

## 🇬🇧 English

A free Telegram fishing bot for beginners. Drop a location pin and it tells you:

- 🎯 **Which body of water you're standing on** right now (on-site ≤250 m, with point-in-polygon detection for lakes) — or the nearest named water within 5 km
- 🌊 **OSM facts** about the water: depth, salinity, reeds, seasonal/permanent
- 🌤 **Live weather** explained in plain language — what each number means *for the bite* (pressure trend matters most)
- 🌙 **Sun, moonrise/set, moon phase and solunar feeding periods**
- 📊 **A 0–10 bite score** computed separately for peaceful fish and predators, factoring in 6-hour pressure trend, solunar window, dawn/dusk proximity, air & water temperature, wind direction and moon phase — with a full breakdown of *why*
- 🔬 **Real fish observations within 25 km** from iNaturalist + GBIF, with localized names
- 🐟 **Top seasonal fish** with per-species tackle recommendations; observation-confirmed species get a 🔬 badge and ranking boost
- ⚠️ **Current spawning ban** info (Krasnodar Krai) and situational beginner tips

Tuned for Southern Russia (Krasnodar Krai) but works worldwide.

### Quick start

```bash
git clone https://github.com/OctoPassik/fishing-helper-bot
cd fishing-helper-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your BOT_TOKEN from @BotFather
python bot.py
```

In Telegram: open the bot → **Start** → 📎 → *Location* → send any place.

### Data sources (all free, no keys)

[Open-Meteo](https://open-meteo.com) (weather) · [Solunar API](https://solunar.org) (sun/moon/bite) · [OpenStreetMap](https://www.openstreetmap.org) via Overpass (waters) · [iNaturalist](https://api.inaturalist.org) + [GBIF](https://www.gbif.org/developer/occurrence) (fish observations) · own fish-and-tackle database (17 species of Southern Russia).

## License

[MIT](LICENSE) © 2026 Vladimir (OctoPass)

---

## 🇷🇺 Русская версия

Telegram-бот, который по геопозиции подсказывает новичку, *что клюёт*,
*на какую снасть ловить* (поплавок / донка / спиннинг), и *когда лучше
приходить*. Ориентирован на **Краснодарский край**, но работает
по всему миру.

### Что делает

Получает геопозицию → показывает:

- 🎯 на каком водоёме ты стоишь *прямо сейчас* (on-site, ≤250 м) — или 🎣
  ближайший именованный водоём (5 км fallback). Для озёр — ещё и
  point-in-polygon, чтобы лодка на середине лимана опознавалась корректно.
- 🌊 OSM-факты о водоёме: глубина, соль, камыш, пересыхающий/нет
- 🌤 текущую погоду: температура, ветер, давление, облачность, осадки
- 👉 **объяснения простым языком** — что каждая цифра погоды означает
  для клёва (главное — тренд давления, ветер, солнце и зоря)
- 🌙 солнце, восход/закат, фазу луны и solunar-периоды клёва
- 📊 оценку клёва 0/10 — *отдельно* для мирной рыбы и хищника,
  потому что у них разные оптимальные условия. Учитывает:
  - тренд давления за 6 часов (главный фактор)
  - текущее solunar-окно (major / minor)
  - близость к восходу/закату (зоря)
  - температура воздуха и воды (скользящее среднее за 48 ч)
  - направление ветра (сезонно)
  - тренд температуры за 12 часов
  - фаза луны
- 📈 развёрнутые причины оценки — почему клёв именно такой
- 🔬 **реальные наблюдения рыб в 25 км** из iNaturalist + GBIF —
  с русскими названиями и количеством наблюдений
- 🐟 топ-4 рыбы по сезону с персональными рекомендациями по снастям;
  виды, подтверждённые наблюдениями, получают метку 🔬 и сильный буст
  в ранжировании. Если условия благоприятнее для хищника — приоритет
  смещается автоматически.
- ⚠️ актуальный нерестовый запрет (для Краснодарского края)
- 👶 ситуативные советы (ветер, жара, холод, пик solunar)

В `/help` — базовые правила, глоссарий снастей, как читать оценку клёва.

### Установка

```bash
git clone https://github.com/OctoPassik/fishing-helper-bot
cd fishing-helper-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Создай бота через [@BotFather](https://t.me/BotFather) → получи токен → положи в `.env`:

```bash
cp .env.example .env
# отредактируй .env, вставь BOT_TOKEN=...
```

### Запуск

```bash
python bot.py
```

Открой своего бота в Telegram, нажми **Start**, затем 📎 → *Геопозиция* →
отправь любое место. Бот пришлёт подробный отчёт.

### Источники данных (все бесплатные, без ключей)

- **Погода** — [Open-Meteo](https://open-meteo.com)
- **Солнце/луна/клёв** — [Solunar API](https://solunar.org)
- **Водоёмы** — [OpenStreetMap](https://www.openstreetmap.org) через Overpass API
- **Наблюдения рыб** — [iNaturalist API](https://api.inaturalist.org) (с
  `locale=ru` для русских названий) и
  [GBIF Occurrence API](https://www.gbif.org/developer/occurrence)
  (включая [датасет Fish occurrence in the Kuban River Basin](https://doi.org/10.3897/BDJ.9.e76701))
- **Рыбы и снасти** — собственная база (17 видов юга России) с латинскими
  именами для связки с внешними API наблюдений

### Структура

```
fishing-helper-bot/
├── bot.py                        # aiogram-обработчики + точка входа
├── services/
│   ├── weather.py                # Open-Meteo (current + 24h hourly history)
│   ├── solunar.py                # solunar.org API
│   ├── waters.py                 # Overpass: on-site / nearest water + PIP
│   ├── inaturalist.py            # клиент iNaturalist API (locale=ru)
│   ├── gbif.py                   # клиент GBIF Occurrence API
│   ├── fish_observations.py      # facade: merge iNat+GBIF + LRU cache
│   ├── fish_db.py                # база рыб + резолвер латинских имён
│   ├── bite.py                   # продвинутый движок оценки клёва
│   └── report.py                 # сборка отчёта + explainers
├── requirements.txt
├── .env.example
└── README.md
```

### Ограничения и отказ от ответственности

- Прогноз клёва — эвристика, не гарантия.
- База рыб ориентирована на юг России. Для Сибири/Севера рекомендации
  будут менее точными.
- Нерестовые запреты указаны справочно — *всегда проверяй актуальные
  правила рыболовства перед выездом*.
- Не поощряется браконьерство. Лови этично, забирай мусор с собой.

### Лицензия

[MIT](LICENSE) © 2026 Vladimir (OctoPass)
