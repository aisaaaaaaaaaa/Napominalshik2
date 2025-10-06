# main.py
import os
import re
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple

import dateparser
from dateparser.search import search_dates
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========== Настройки ==========
LOG_LEVEL = logging.INFO
TIMEZONE_NAME = "Asia/Almaty"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
PORT = int(os.getenv("PORT", 10000))

DB_FILE = "reminders.db"

# ========== Логирование ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# ========== БД ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        text TEXT,
        remind_time_iso TEXT,  -- stored as UTC ISO string
        sent INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_reminder_db(user_id: int, chat_id: int, text: str, remind_time_iso_utc: str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders (user_id, chat_id, text, remind_time_iso, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, chat_id, text, remind_time_iso_utc, datetime.utcnow().isoformat())
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid

def get_due_reminders_db(now_iso_utc: str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, text, remind_time_iso FROM reminders WHERE sent=0 AND remind_time_iso<=? ORDER BY remind_time_iso ASC", (now_iso_utc,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_sent_db(rid: int):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
    conn.commit()
    conn.close()

def list_reminders_db(chat_id: int):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, text, remind_time_iso FROM reminders WHERE chat_id=? AND sent=0 ORDER BY remind_time_iso", (chat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def cancel_reminder_db(chat_id: int, rid: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id FROM reminders WHERE id=? AND chat_id=? AND sent=0", (rid, chat_id))
    found = cur.fetchone()
    if not found:
        conn.close()
        return False
    cur.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return True

# ========== Парсер даты/времени ==========
def parse_datetime_from_text(text: str) -> Tuple[Optional[str], Optional[datetime]]:
    """
    Попытка найти фразу времени в произвольном тексте.
    Возвращает (matched_text, datetime) или (None, None).
    Datetime возвращается с tzinfo (Asia/Almaty) и затем мы конвертируем в UTC при сохранении.
    """
    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": TIMEZONE_NAME,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }

    # Попробовать найти даты/времена в тексте
    try:
        found = search_dates(text, languages=["ru"], settings=settings)
    except Exception as e:
        logger.debug("search_dates failed: %s", e)
        found = None

    if found:
        # выбираем последний найденный фрагмент (часто это наиболее релевантный)
        match_text, dt = found[-1]
        if dt is not None:
            # Если dt не aware — считаем, что это TIMEZONE
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TIMEZONE)
            return match_text, dt
    # fallback: поддержка короткой формы "через 5 минут" или "5 минут" в начале
    m = re.match(r'^\s*(?:через\s+)?(\d{1,5})\s*(минут|мин|м|час|ч|h|hours)?\b', text, flags=re.I)
    if m:
        num = int(m.group(1))
        unit = (m.group(2) or "").lower()
        if "час" in unit or unit in ("h","ч","hours"):
            dt = datetime.now(TIMEZONE) + timedelta(hours=num)
        else:
            dt = datetime.now(TIMEZONE) + timedelta(minutes=num)
        return m.group(0).strip(), dt.replace(tzinfo=TIMEZONE)
    return None, None

# ========== Хэндлеры ==========
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот-напоминалка.\n\n"
        "Примеры команд/текста:\n"
        "- Напомни завтра в 10:00 сходить в магазин\n"
        "- Через 5 минут проверить чайник\n"
        "- /new 2025-10-07 10:00 купить хлеб\n\n"
        "Команды:\n"
        "/new <время> <текст> — новый напоминалка\n"
        "/list — список ближайших напоминаний\n"
        "/cancel <id> — отменить напоминание по id"
    )

async def new_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # поддержим сразу формат "/new <текст>" — дальше логика в общем обработчике
    text = update.message.text or ""
    payload = text[len("/new"):].strip()
    if not payload:
        await update.message.reply_text("Использование: /new <время> <текст>\nПример: /new завтра в 10:00 купить хлеб")
        return
    # перенаправляем к общему обработчику (тот же парсинг)
    await handle_message_inner(update, context, payload)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    await handle_message_inner(update, context, text)

async def handle_message_inner(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    original = text.strip()

    # Попытка парсинга
    match_text, dt = parse_datetime_from_text(original)
    if not dt:
        await update.message.reply_text(
            "⏰ Не понял время напоминания.\nПопробуй:\n"
            "- 'Напомни завтра в 10:00 сходить в магазин'\n"
            "- 'Через 5 минут помыть посуду'\n"
            "- '/new 2025-10-07 10:00 купить хлеб'"
        )
        return

    # удалим матченную фразу из текста (один раз, без учёта регистра)
    try:
        pattern = re.escape(match_text)
        reminder_text = re.sub(pattern, "", original, count=1, flags=re.I).strip()
    except Exception:
        reminder_text = original

    # убираем ведущие слова "напомни"
    reminder_text = re.sub(r'^\s*(?:напомни|пожалуйста|помоги|напиши)\b[:,]?\s*', '', reminder_text, flags=re.I).strip()

    if not reminder_text:
        reminder_text = "Напоминание"

    # Приведём dt к aware (если вдруг) и к UTC для хранения
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TIMEZONE)
    dt_utc = dt.astimezone(ZoneInfo("UTC"))
    iso_utc = dt_utc.isoformat()

    rid = add_reminder_db(user_id, chat_id, reminder_text, iso_utc)

    # Подтверждение пользователю — показываем локальное время в Asia/Almaty
    dt_local = dt_utc.astimezone(TIMEZONE)
    await update.message.reply_text(
        f"✅ Напоминание #{rid} создано:\n"
        f"📌 Что: {reminder_text}\n"
        f"🕒 Когда: {dt_local.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    logger.info(f"Создано напоминание #{rid} для {chat_id}: {reminder_text} at {iso_utc}")

async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = list_reminders_db(chat_id)
    if not rows:
        await update.message.reply_text("Нет активных напоминаний.")
        return
    lines = []
    for rid, text, remind_iso in rows:
        try:
            dt_utc = datetime.fromisoformat(remind_iso)
            dt_local = dt_utc.astimezone(TIMEZONE)
            lines.append(f"#{rid} — {dt_local.strftime('%Y-%m-%d %H:%M')} — {text}")
        except Exception:
            lines.append(f"#{rid} — {remind_iso} — {text}")
    await update.message.reply_text("Список напоминаний:\n" + "\n".join(lines))

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /cancel <id>")
        return
    try:
        rid = int(args[0])
    except ValueError:
        await update.message.reply_text("id должен быть числом.")
        return
    ok = cancel_reminder_db(chat_id, rid)
    if ok:
        await update.message.reply_text(f"✅ Напоминание #{rid} отменено.")
    else:
        await update.message.reply_text(f"❌ Напоминание #{rid} не найдено или уже отправлено.")

# ========== Periodic checker (job_queue) ==========
async def check_due_reminders(context: ContextTypes.DEFAULT_TYPE):
    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    now_iso = now_utc.isoformat()
    due = get_due_reminders_db(now_iso)
    for rid, chat_id, text, remind_iso in due:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
            mark_sent_db(rid)
            logger.info(f"Отправлено напоминание #{rid} to {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания #{rid}: {e}")

# ========== MAIN ==========
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Хэндлеры
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("new", new_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # job_queue — проверяем каждую минуту
    app.job_queue.run_repeating(check_due_reminders, interval=60, first=10)

    logger.info("🚀 Запуск webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
