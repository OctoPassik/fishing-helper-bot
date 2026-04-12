"""Telegram-бот «Рыбалка-помощник новичку».

Запуск:
    pip install -r requirements.txt
    echo "BOT_TOKEN=..." > .env
    python bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

from services.fish_observations import fetch_observations
from services.report import build_report, smart_truncate
from services.solunar import fetch_solunar
from services.waters import find_nearest_water, find_wide_waters
from services.weather import fetch_weather

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fishing-bot")


HELLO = (
    "🎣 *Рыболовный помощник для новичков*\n\n"
    "Пришли мне *геопозицию* того места, где хочешь порыбачить "
    "(скрепка 📎 → Геопозиция), и я расскажу:\n"
    "• какой ближайший водоём рядом\n"
    "• какая рыба сейчас клюёт и когда лучше приходить\n"
    "• на какие снасти её ловить — поплавок, донка или спиннинг\n"
    "• погоду, давление, ветер, фазу луны\n"
    "• советы новичку с учётом условий\n\n"
    "Нажми кнопку ниже 👇 или пришли любую геопозицию через 📎"
)

HELP = (
    "*Как пользоваться ботом*\n"
    "1. Нажми 📎 в Telegram → *Геопозиция*\n"
    "2. Выбери место на карте или отправь *Мою геопозицию*\n"
    "3. Я расскажу что клюёт, на что ловить, и объясню погоду.\n\n"
    "*Команды:*\n"
    "/start — приветствие и кнопка геопозиции\n"
    "/help — эта справка\n"
    "/about — откуда я беру данные\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📚 *Что такое снасти (если слышишь впервые)*\n\n"
    "• *Поплавок* — обычная удочка 4–5 м с поплавком на леске. "
    "Самая простая снасть. Леска 0.16–0.20, крючок №10–14. "
    "Ловит карася, плотву, окуня, краснопёрку.\n\n"
    "• *Донка / фидер* — удочка без поплавка. Грузик и крючок с "
    "наживкой лежат на дне, ты ждёшь поклёвки по кончику удилища. "
    "Ловит крупную мирную рыбу: сазана, леща, карпа, сома.\n\n"
    "• *Спиннинг* — короткая палка с катушкой. На крючке не наживка, "
    "а *приманка* (блесна, воблер, силиконка), которую забрасываешь и "
    "подматываешь. Ловит хищника: щуку, судака, окуня, жереха.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👶 *Базовые правила новичка*\n\n"
    "• *Лучшее время* — заря: за 30–40 мин до восхода и за час до заката.\n"
    "• *Подходи к воде тихо*. Рыба слышит топот через воду.\n"
    "• На *щуку* — всегда металлический поводок, иначе перекусит.\n"
    "• В *рюкзак*: подсак, ножницы, запасные крючки, вода, еда.\n"
    "• *Пойманную мелочь* отпускай — пусть подрастёт.\n"
    "• *Мусор забирай с собой* ♻️ — птицы и звери гибнут "
    "от брошенной лески.\n"
    "• *Проверь законы* своего региона: сроки нереста, норма вылова, "
    "минимальный размер рыбы. Штрафы в России — от 2 000 ₽ за особь.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📊 *Как читать оценку клёва*\n\n"
    "Бот считает отдельно для *мирной* рыбы и *хищника* — "
    "у них разные оптимальные условия.\n"
    "• *9–10/10* — супер, беги на воду.\n"
    "• *7–8/10* — хороший клёв, будет улов.\n"
    "• *5–6/10* — средне, придётся поискать.\n"
    "• *3–4/10* — слабо, мирная почти спит.\n"
    "• *0–2/10* — пересиди дома.\n\n"
    "*Главное для клёва* — *стабильное давление* и *заря*. "
    "Всё остальное — вторично.\n\n"
    "_Бот заточен под Краснодарский край, но работает по всему миру._"
)

ABOUT = (
    "*Источники данных:*\n"
    "• Погода — [Open-Meteo](https://open-meteo.com) "
    "(бесплатно, без API-ключа)\n"
    "• Солнце, луна и лунный клёв — [Solunar API](https://solunar.org)\n"
    "• Ближайшие водоёмы — [OpenStreetMap](https://www.openstreetmap.org) "
    "через Overpass API\n"
    "• База рыб и снастей — собрана вручную под Краснодарский край\n\n"
    "_Бот не даёт 100% гарантий клёва — используй как подсказку, "
    "а не как закон._"
)

FALLBACK = (
    "Пришли *геопозицию* через скрепку 📎 → Геопозиция — "
    "и я расскажу, что сейчас клюёт на ближайшем водоёме 🎣"
)


def _tz_hours_from_weather(weather: dict) -> int:
    """Return signed integer UTC offset in hours from Open-Meteo response."""
    offset = weather.get("utc_offset_seconds") if weather else None
    if offset is None:
        return 0
    try:
        seconds = int(offset)
    except (TypeError, ValueError):
        return 0
    # round-toward-zero to handle fractional half-hour zones (e.g. +5:30 → 5)
    return int(seconds / 3600)


async def _safe_send_plain(msg: Message, text: str) -> None:
    """Send a plain-text message, splitting if necessary to respect Telegram
    4096-character limit."""
    max_len = 4000
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        cut = remaining[:max_len]
        nl = cut.rfind("\n")
        if nl < max_len // 2:
            nl = max_len
        parts.append(remaining[:nl])
        remaining = remaining[nl:].lstrip("\n")
    parts.append(remaining)
    for part in parts:
        await msg.answer(part, parse_mode=None, disable_web_page_preview=True)


def _make_water_keyboard(waters: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard from wide water search results."""
    buttons = []
    for i, w in enumerate(waters):
        wtype = (w.get("type") or "водоём").capitalize()
        name = w.get("name") or "?"
        dist = w.get("distance_km", "?")
        label = f"{wtype} {name} ({dist} км)"
        if len(label) > 50:
            label = label[:47] + "…"
        # callback_data max 64 bytes: "w:{index}:{lat},{lon}"
        clat = w.get("lat") or 0
        clon = w.get("lon") or 0
        cb = f"w:{i}:{clat:.4f},{clon:.4f}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# In-memory store for wide search results per user (chat_id -> list)
_wide_cache: dict[int, tuple[float, float, list[dict]]] = {}


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    location_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    @dp.message(CommandStart())
    async def cmd_start(msg: Message) -> None:
        await msg.answer(HELLO, reply_markup=location_kb, disable_web_page_preview=True)

    @dp.message(Command("help"))
    async def cmd_help(msg: Message) -> None:
        await msg.answer(HELP, disable_web_page_preview=True)

    @dp.message(Command("about"))
    async def cmd_about(msg: Message) -> None:
        await msg.answer(ABOUT, disable_web_page_preview=True)

    @dp.message(F.location)
    async def on_location(msg: Message) -> None:
        if msg.location is None:
            return  # defensive: filter already guarantees this
        lat = float(msg.location.latitude)
        lon = float(msg.location.longitude)
        user = msg.from_user.id if msg.from_user else "?"
        log.info("location from %s: %.5f %.5f", user, lat, lon)

        progress = await msg.answer(
            "🔎 Смотрю погоду, луну, водоём и наблюдения рыб…",
        )

        weather_task = asyncio.create_task(fetch_weather(lat, lon))
        water_task = asyncio.create_task(find_nearest_water(lat, lon))
        obs_task = asyncio.create_task(fetch_observations(lat, lon, radius_km=25))

        async def _cancel_quietly(task: asyncio.Task) -> None:
            if task.done():
                return
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # --- погода обязательна ---
        try:
            weather = await weather_task
        except Exception as exc:
            log.exception("weather fetch failed")
            await _cancel_quietly(water_task)
            await _cancel_quietly(obs_task)
            await progress.edit_text(
                "❌ Не удалось получить прогноз погоды: "
                f"{type(exc).__name__}. Попробуй ещё раз через минуту."
            )
            return

        # --- solunar (не критично) ---
        tz_hours = _tz_hours_from_weather(weather)
        solunar: dict | None = None
        try:
            solunar = await fetch_solunar(lat, lon, date.today(), tz_hours)
        except Exception as exc:
            log.warning("solunar fetch failed: %s", exc)

        # --- водоёмы (не критично) ---
        water: dict | None = None
        try:
            water = await water_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("overpass fetch failed: %s", exc)

        # --- Если водоём не найден в 5 км — ищем в 100 км и даём выбор ---
        if water is None:
            try:
                await progress.edit_text("🔎 Водоём рядом не найден, ищу в радиусе 100 км…")
                wide_waters = await find_wide_waters(lat, lon, max_results=8)
            except Exception as exc:
                log.warning("wide waters search failed: %s", exc)
                wide_waters = []

            if wide_waters:
                await _cancel_quietly(obs_task)
                chat_id = msg.chat.id
                _wide_cache[chat_id] = (lat, lon, wide_waters)
                kb = _make_water_keyboard(wide_waters)
                await progress.edit_text(
                    "📍 В радиусе 5 км водоёмов не нашлось.\n"
                    "Выбери водоём из списка — я покажу отчёт для него:",
                    reply_markup=kb,
                )
                return

        # --- наблюдения рыб (не критично) ---
        observations: list[dict] = []
        try:
            observations = await obs_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("fish observations fetch failed: %s", exc)

        # --- сборка отчёта ---
        await _send_report(msg, progress, lat, lon, weather, solunar, water, observations)

    @dp.callback_query(lambda cb: cb.data and cb.data.startswith("w:"))
    async def on_water_chosen(cb: CallbackQuery) -> None:
        """Handle inline keyboard water body selection."""
        await cb.answer()
        chat_id = cb.message.chat.id if cb.message else 0
        cached = _wide_cache.pop(chat_id, None)
        if not cached:
            if cb.message:
                await cb.message.edit_text("⏳ Сессия истекла. Отправь геопозицию заново.")
            return

        user_lat, user_lon, waters = cached

        # Parse callback data: "w:{index}:{lat},{lon}"
        parts = (cb.data or "").split(":")
        try:
            idx = int(parts[1])
            chosen = waters[idx]
        except (IndexError, ValueError):
            if cb.message:
                await cb.message.edit_text("❌ Ошибка выбора. Отправь геопозицию заново.")
            return

        if cb.message:
            await cb.message.edit_text(
                f"🔎 Строю отчёт для {chosen.get('type', 'водоём')} "
                f"{chosen.get('name', '?')}…",
                reply_markup=None,
            )

        # Build a water dict compatible with report
        water_for_report: dict = {
            "name": chosen.get("name"),
            "type": chosen.get("type", "водоём"),
            "distance_km": chosen.get("distance_km", 0),
            "on_site": False,
            "inside": False,
            "tags": chosen.get("tags", {}),
        }

        # Fetch weather + solunar for user's location
        try:
            weather = await fetch_weather(user_lat, user_lon)
        except Exception:
            if cb.message:
                await cb.message.edit_text("❌ Не удалось получить погоду. Попробуй снова.")
            return

        tz_hours = _tz_hours_from_weather(weather)
        solunar: dict | None = None
        try:
            solunar = await fetch_solunar(user_lat, user_lon, date.today(), tz_hours)
        except Exception:
            pass

        observations: list[dict] = []
        try:
            observations = await fetch_observations(user_lat, user_lon, radius_km=25)
        except Exception:
            pass

        await _send_report(
            cb.message, cb.message, user_lat, user_lon,
            weather, solunar, water_for_report, observations,
        )

    async def _send_report(
        msg: Message, progress: Message,
        lat: float, lon: float,
        weather: dict, solunar: dict | None,
        water: dict | None, observations: list[dict],
    ) -> None:
        """Build report and send it, with markdown fallback."""
        try:
            report = build_report(
                lat=lat, lon=lon, weather=weather,
                solunar=solunar, water=water,
                today=date.today(), observations=observations,
            )
        except Exception as exc:
            log.exception("report building failed")
            try:
                await progress.edit_text(
                    f"❌ Ошибка составления отчёта: {type(exc).__name__}"
                )
            except Exception:
                pass
            return

        report = smart_truncate(report)

        try:
            await progress.edit_text(
                report,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest as exc:
            log.warning("markdown edit failed: %s", exc)
        except Exception as exc:
            log.warning("progress edit failed: %s", exc)

        try:
            await progress.delete()
        except Exception:
            pass
        await _safe_send_plain(msg, report)

    @dp.message()
    async def fallback(msg: Message) -> None:
        await msg.answer(FALLBACK, reply_markup=location_kb)

    return dp


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан. Создай .env со строкой "
            "`BOT_TOKEN=...` или задай переменную окружения."
        )
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = create_dispatcher()
    log.info("Bot started")
    try:
        # allowed_updates=None позволяет aiogram самому подобрать список
        # апдейтов на основе зарегистрированных хендлеров.
        await dp.start_polling(bot, allowed_updates=None)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
