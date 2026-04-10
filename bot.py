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
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

from services.fish_observations import fetch_observations
from services.report import build_report, smart_truncate
from services.solunar import fetch_solunar
from services.waters import find_nearest_water
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
    "*Как пользоваться:*\n"
    "1. Нажми 📎 в Telegram → *Геопозиция*\n"
    "2. Выбери место на карте → *Отправить выбранную геопозицию*\n"
    "   (или *Мою геопозицию* — если уже на месте)\n"
    "3. Я найду ближайший водоём, посмотрю погоду и луну, "
    "и расскажу что, на что и когда клюёт.\n\n"
    "*Команды:*\n"
    "/start — приветствие и кнопка геопозиции\n"
    "/help — эта справка\n"
    "/about — откуда я беру данные\n\n"
    "_Бот заточен под Краснодарский край, но работает "
    "по всему миру._"
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

        # --- наблюдения рыб (не критично) ---
        observations: list[dict] = []
        try:
            observations = await obs_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("fish observations fetch failed: %s", exc)

        # --- сборка отчёта ---
        try:
            report = build_report(
                lat=lat,
                lon=lon,
                weather=weather,
                solunar=solunar,
                water=water,
                today=date.today(),
                observations=observations,
            )
        except Exception as exc:
            log.exception("report building failed")
            await progress.edit_text(
                f"❌ Ошибка составления отчёта: {type(exc).__name__}"
            )
            return

        # smart_truncate уже применён внутри build_report, но подстрахуемся.
        report = smart_truncate(report)

        # --- отправка: пытаемся markdown, при ошибке делаем чистый текст ---
        try:
            await progress.edit_text(
                report,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest as exc:
            # Чаще всего — can't parse entities. Удалим прогресс и пошлём
            # обычный текст новым сообщением.
            log.warning("markdown edit failed: %s", exc)
        except Exception as exc:
            log.warning("progress edit failed: %s", exc)

        # Пытаемся удалить прогресс, чтобы не оставлять «смотрю…».
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
