# main.py
import logging
import sqlite3
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ================== НАСТРОЙКИ ==================
TOKEN = "7309853259:AAEgnNjHnRLBWMt-0K6VRkJTXIczj2HvPd0"   # замени на свой
WEBHOOK_URL = "https://napominalshik2.onrender.com/webhook"

# ================== ЛОГИ ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== SQLite ==================
def init_db():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            remind_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_reminder(user_id, text, remind_at):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reminders (user_id, text, remind_at) VALUES (?, ?, ?)",
        (user_id, text, remind_at)
    )
    conn.commit()
    conn.close()

def get_user_reminders(user_id):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, text, remind_at FROM reminders WHERE user_id=?", (user_id,))
    reminders = cursor.fetchall()
    conn.close()
    return reminders

# ================== APScheduler ==================
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Almaty"))

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(job.chat_id, text=f"⏰ Напоминание: {job.data}")

# ================== ОБРАБОТЧИКИ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой напоминальщик.\n\n"
        "Используй команды:\n"
        "👉 /new текст время — создать напоминание\n"
        "👉 /list — список твоих напоминаний\n"
        "👉 /help — помощь"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Примеры:\n"
        "/new купить хлеб 2025-10-07 09:00\n"
        "/list — список напоминаний"
    )

async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 3:
            await update.message.reply_text("⚠ Формат: /new <текст> YYYY-MM-DD HH:MM")
            return

        text = " ".join(context.args[:-2])
        date_str = context.args[-2] + " " + context.args[-1]
        remind_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M")

        user_id = update.message.chat_id
        add_reminder(user_id, text, remind_at.isoformat())

        # планируем задачу
        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=remind_at, timezone=pytz.timezone("Asia/Almaty")),
            args=[context],
            kwargs={"chat_id": user_id, "data": text}
        )

        await update.message.reply_text(f"✅ Напоминание создано: {text} в {remind_at}")
    except Exception as e:
        logger.error(f"Ошибка при создании напоминания: {e}")
        await update.message.reply_text("❌ Ошибка! Проверь формат даты.")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    reminders = get_user_reminders(user_id)
    if not reminders:
        await update.message.reply_text("ℹ У тебя нет напоминаний.")
    else:
        msg = "📋 Твои напоминания:\n"
        for r in reminders:
            msg += f"• {r[1]} (в {r[2]})\n"
        await update.message.reply_text(msg)

# ================== MAIN ==================
def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("new", new_reminder))
    app.add_handler(CommandHandler("list", list_reminders))

    # запуск планировщика
    scheduler.start()

    # webhook
    logger.info("🚀 Запуск через Webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
