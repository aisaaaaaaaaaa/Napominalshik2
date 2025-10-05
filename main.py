import logging
import os
import pytz
import sqlite3
from datetime import datetime

import dateparser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- ЛОГИ -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- НАСТРОЙКИ -----------------
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
PORT = int(os.getenv("PORT", 10000))

# Таймзона
TIMEZONE = pytz.timezone("Asia/Almaty")

# ----------------- БД -----------------
def init_db():
    conn = sqlite3.connect("reminders.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    text TEXT,
                    remind_time TEXT
                )""")
    conn.commit()
    conn.close()

def save_reminder(chat_id: int, text: str, remind_time: str):
    conn = sqlite3.connect("reminders.db")
    c = conn.cursor()
    c.execute("INSERT INTO reminders (chat_id, text, remind_time) VALUES (?, ?, ?)",
              (chat_id, text, remind_time))
    conn.commit()
    conn.close()

def get_due_reminders():
    conn = sqlite3.connect("reminders.db")
    c = conn.cursor()
    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    c.execute("SELECT id, chat_id, text FROM reminders WHERE remind_time <= ?", (now,))
    reminders = c.fetchall()
    for r in reminders:
        c.execute("DELETE FROM reminders WHERE id=?", (r[0],))
    conn.commit()
    conn.close()
    return reminders

# ----------------- APSCHEDULER -----------------
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

async def send_reminder(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания: {e}")

async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    reminders = get_due_reminders()
    for _, chat_id, text in reminders:
        await send_reminder(chat_id, text, context)

# ----------------- КОМАНДЫ -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋 Я бот-напоминальщик!\n"
        "Примеры:\n"
        "• напомни завтра в 10:00 сходить в магазин\n"
        "• через 15 минут полить цветы\n"
        "• завтра в 18:30 встреча\n"
        "• через час позвонить маме"
    )

async def add_reminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Классическая команда /remind"""
    try:
        dt_str = context.args[0] + " " + context.args[1]
        text = " ".join(context.args[2:])
        remind_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        remind_time = TIMEZONE.localize(remind_time)

        save_reminder(update.effective_chat.id, text, remind_time.strftime("%Y-%m-%d %H:%M"))

        await update.message.reply_text(f"✅ Напоминание сохранено: {text} в {remind_time}")
    except Exception as e:
        logger.error(f"Ошибка при создании напоминания: {e}")
        await update.message.reply_text("❌ Используй формат: /remind YYYY-MM-DD HH:MM ТЕКСТ")

async def parse_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Парсим обычный текст пользователя"""
    user_text = update.message.text.strip()

    # Пробуем найти дату/время в тексте
    dt = dateparser.parse(user_text, languages=["ru"], settings={"TIMEZONE": "Asia/Almaty", "RETURN_AS_TIMEZONE_AWARE": True})

    if not dt:
        await update.message.reply_text("❌ Не понял время. Попробуй написать по-другому (например: завтра в 10:00 или через 15 минут).")
        return

    # Текст напоминания = оригинальный текст без даты
    text = user_text

    save_reminder(update.effective_chat.id, text, dt.strftime("%Y-%m-%d %H:%M"))
    await update.message.reply_text(f"✅ Напоминание сохранено: {text} в {dt.strftime('%Y-%m-%d %H:%M')}")

# ----------------- MAIN -----------------
def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("remind", add_reminder_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, parse_reminder))

    scheduler.add_job(
        lambda: check_reminders_job(application.bot),
        trigger="interval",
        minutes=1
    )
    scheduler.start()

    logger.info("🚀 Запуск через Webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook",
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
