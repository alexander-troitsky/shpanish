"""Telegram-бот интервального повторения испанских слов (aiogram 3.x)."""
import asyncio
import time
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import db
import sheets
from srs import Session

BOT: Bot = None
dp = Dispatcher()

# Состояние сессий в памяти: chat_id -> {'s': Session, 'msg_id': int, 'last_ts': float}
SESS = {}


# ---------- сборка/доступ к сессии ----------
def build_session(chat_id) -> Session:
    today = config.today_str()
    words = sheets.load_words()
    known = db.known_es()
    new_pool = [w for w in words if w["es"] not in known]
    remaining_quota = max(0, config.DAILY_NEW - db.get_new_introduced(today))
    reviews = db.due_cards(today)
    s = Session(new_pool, remaining_quota, reviews)
    SESS[chat_id] = {"s": s, "msg_id": None, "last_ts": time.time()}
    return s


def track_time(chat_id):
    """Засчитываем активное время с поправкой на простой."""
    st = SESS.get(chat_id)
    if not st:
        return
    now = time.time()
    delta = min(now - st["last_ts"], config.IDLE_CAP_SECONDS)
    db.add_active_seconds(config.today_str(), delta)
    st["last_ts"] = now


# ---------- рендер ----------
def card_text(word, direction, answer_shown):
    if direction == "es_ru":
        tag = "🇪🇸 → 🇷🇺"
        front, back = word["es"], word["ru"]
    else:
        tag = "🇷🇺 → 🇪🇸"
        front, back = word["ru"], word["es"]
    if not answer_shown:
        return f"<b>{front}</b>\n\n<i>{tag}</i>"
    ctx = word.get("ctx") or ""
    ctx_line = f"\n\n<code>{ctx}</code>" if ctx else ""
    return f"<b>{front}</b>\n\n➡️ {back}{ctx_line}\n\n<i>{tag}</i>"


def card_kb(answer_shown, gradable):
    if not answer_shown:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔍 Проверить", callback_data="chk")]])
    if gradable:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Помню", callback_data="know"),
            InlineKeyboardButton(text="❌ Не помню", callback_data="dont")]])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Дальше →", callback_data="nxt")]])


async def render(chat_id, step):
    """Показывает очередной шаг сессии новым сообщением."""
    st = SESS[chat_id]
    if step["kind"] == "card":
        w, d, g = step["word"], step["direction"], step["gradable"]
        msg = await BOT.send_message(chat_id, card_text(w, d, False),
                                     reply_markup=card_kb(False, g), parse_mode="HTML")
        st["msg_id"] = msg.message_id
    elif step["kind"] == "more_new_prompt":
        rows = [[InlineKeyboardButton(text=f"➕ Ещё {config.DAILY_NEW} новых", callback_data="more")]]
        if step["reviews_due"]:
            rows.append([InlineKeyboardButton(
                text=f"▶️ К повторениям ({step['reviews_due']})", callback_data="toreview")])
        else:
            rows.append([InlineKeyboardButton(text="✅ Завершить", callback_data="fin")])
        await BOT.send_message(
            chat_id,
            f"✅ Новые слова на сегодня пройдены (+{SESS[chat_id]['s'].introduced_this_session}).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif step["kind"] == "finished":
        await finish(chat_id)


async def finish(chat_id):
    st = SESS.pop(chat_id, None)
    db.set_quota_done(config.today_str(), True)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"➕ Ещё {config.DAILY_NEW} новых", callback_data="more_fresh")]])
    intro = st["s"].introduced_this_session if st else 0
    await BOT.send_message(
        chat_id,
        f"🎉 Готово на сегодня!\nНовых выучено в этой сессии: {intro}.\n"
        f"Напоминания до завтра отключаю. Запустить вручную — /review.",
        reply_markup=kb)


async def reveal_current(chat_id, cq: CallbackQuery):
    st = SESS.get(chat_id)
    if not st:
        return
    s = st["s"]
    s.reveal()
    await cq.message.edit_text(
        card_text(s.current, s.direction, True),
        reply_markup=card_kb(True, s.gradable), parse_mode="HTML")


async def advance(chat_id, step):
    # убираем кнопки с предыдущей карточки, чтобы не нажать дважды
    st = SESS.get(chat_id)
    if st and st.get("msg_id"):
        try:
            await BOT.edit_message_reply_markup(chat_id, st["msg_id"], reply_markup=None)
        except Exception:
            pass
    await render(chat_id, step)


# ---------- хендлеры ----------
@dp.message(Command("start"))
async def cmd_start(m: Message):
    db.set_meta("owner_chat_id", m.chat.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ Начать", callback_data="begin")]])
    await m.answer(
        "¡Hola! Я бот для интервального повторения испанских слов.\n\n"
        "• /review — запустить занятие сейчас\n"
        "• /stats — статистика\n"
        "• /stop — прервать занятие\n\n"
        "Напоминать буду раз в час с "
        f"{config.REMINDER_START}:00 до {config.REMINDER_END}:00.",
        reply_markup=kb)


async def start_session(chat_id):
    s = build_session(chat_id)
    await render(chat_id, s.next_step())


@dp.message(Command("review"))
async def cmd_review(m: Message):
    db.set_meta("owner_chat_id", m.chat.id)
    await start_session(m.chat.id)


@dp.message(Command("stop"))
async def cmd_stop(m: Message):
    SESS.pop(m.chat.id, None)
    await m.answer("Занятие прервано. Возобновить — /review.")


@dp.callback_query(F.data == "begin")
async def cb_begin(cq: CallbackQuery):
    await cq.answer()
    await start_session(cq.message.chat.id)


@dp.callback_query(F.data == "chk")
async def cb_check(cq: CallbackQuery):
    await cq.answer()
    track_time(cq.message.chat.id)
    await reveal_current(cq.message.chat.id, cq)


@dp.callback_query(F.data == "nxt")
async def cb_next(cq: CallbackQuery):
    await cq.answer()
    cid = cq.message.chat.id
    track_time(cid)
    st = SESS.get(cid)
    if not st:
        return
    await advance(cid, st["s"].next_step())


@dp.callback_query(F.data.in_({"know", "dont"}))
async def cb_grade(cq: CallbackQuery):
    await cq.answer("✅" if cq.data == "know" else "🔁")
    cid = cq.message.chat.id
    track_time(cid)
    st = SESS.get(cid)
    if not st:
        return
    await advance(cid, st["s"].grade(cq.data == "know"))


@dp.callback_query(F.data == "more")
async def cb_more(cq: CallbackQuery):
    await cq.answer()
    cid = cq.message.chat.id
    st = SESS.get(cid)
    if not st:
        return
    await advance(cid, st["s"].add_new())


@dp.callback_query(F.data == "more_fresh")
async def cb_more_fresh(cq: CallbackQuery):
    """Кнопка «ещё новые» после завершения сессии — собираем новую сессию."""
    await cq.answer()
    cid = cq.message.chat.id
    s = build_session(cid)
    step = s.add_new() if not (s.new_quota and s.new_pool) else s.next_step()
    await render(cid, step)


@dp.callback_query(F.data == "toreview")
async def cb_toreview(cq: CallbackQuery):
    await cq.answer()
    cid = cq.message.chat.id
    st = SESS.get(cid)
    if not st:
        return
    await advance(cid, st["s"].next_step())


@dp.callback_query(F.data == "fin")
async def cb_fin(cq: CallbackQuery):
    await cq.answer()
    await finish(cq.message.chat.id)


# ---------- статистика ----------
def fmt_dur(seconds):
    seconds = int(seconds)
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h} ч {m} мин" if h else f"{m} мин"


def stats_text(period):
    today = date.fromisoformat(config.today_str())
    if period == "day":
        frm, label = today.isoformat(), "сегодня"
    elif period == "week":
        frm, label = (today - timedelta(days=7)).isoformat(), "за неделю"
    else:
        frm, label = "0000-01-01", "за всё время"

    steps = db.counts_by_step()
    in_work = sum(steps.values())
    grad_total = db.graduated_count()
    grad_period = db.graduated_since(frm + "T00:00:00")
    secs = db.active_seconds_since(frm)

    lines = [f"📊 Статистика ({label})", ""]
    lines.append(f"🎓 Выучено всего: {grad_total}")
    lines.append(f"🎓 Выучено {label}: {len(grad_period)}")
    lines.append(f"⏱️ Время занятий {label}: {fmt_dur(secs)}")
    lines.append("")
    lines.append(f"📚 В работе: {in_work}")
    for s in sorted(config.STEP_INTERVALS):
        lines.append(f"   ступень {s} ({config.STEP_INTERVALS[s]} дн): {steps.get(s, 0)}")
    if grad_period:
        shown = ", ".join(grad_period[:30])
        more = "" if len(grad_period) <= 30 else f" … (+{len(grad_period) - 30})"
        lines.append("")
        lines.append(f"Выученные {label}: {shown}{more}")
    return "\n".join(lines)


def stats_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Сегодня", callback_data="st_day"),
        InlineKeyboardButton(text="Неделя", callback_data="st_week"),
        InlineKeyboardButton(text="Всё", callback_data="st_all")]])


@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    await m.answer(stats_text("week"), reply_markup=stats_kb())


@dp.callback_query(F.data.startswith("st_"))
async def cb_stats(cq: CallbackQuery):
    await cq.answer()
    period = {"st_day": "day", "st_week": "week", "st_all": "all"}[cq.data]
    await cq.message.edit_text(stats_text(period), reply_markup=stats_kb())


# ---------- напоминания ----------
async def reminder_tick():
    chat_id = db.get_meta("owner_chat_id")
    if not chat_id:
        return
    chat_id = int(chat_id)
    if db.is_quota_done(config.today_str()):
        return
    if chat_id in SESS:  # занятие уже идёт — не дёргаем
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ Позаниматься", callback_data="begin")]])
    await BOT.send_message(chat_id, "⏰ Время повторить испанские слова!", reply_markup=kb)


# ---------- запуск ----------
async def main():
    global BOT
    db.init_db()
    BOT = Bot(config.BOT_TOKEN)
    scheduler = AsyncIOScheduler(timezone=config.TZ)
    scheduler.add_job(reminder_tick, "cron",
                      hour=f"{config.REMINDER_START}-{config.REMINDER_END}", minute=0)
    scheduler.start()
    print("Бот запущен.")
    await dp.start_polling(BOT)


if __name__ == "__main__":
    asyncio.run(main())
