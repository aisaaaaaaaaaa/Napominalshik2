import os
import logging
import sqlite3
import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from apscheduler.schedulers.background import BackgroundScheduler
import dateparser

# ===================== Логирование =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== Конфигурация =====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
PORT = int(os.getenv("PORT", 10000))

DB_FILE = "reminders.db"

# Глобальная переменная для event loop
MAIN_LOOP = None

# ===================== Работа с БД =====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  text TEXT,
                  remind_time TEXT,
                  sent INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def add_reminder(chat_id, text, remind_time):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (chat_id, text, remind_time) VALUES (?, ?, ?)",
              (chat_id, text, remind_time))
    conn.commit()
    conn.close()

def get_due_reminders():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT id, chat_id, text FROM reminders WHERE remind_time<=? AND sent=0", (now,))
    reminders = c.fetchall()
    conn.close()
    return reminders

def mark_reminder_sent(reminder_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE reminders SET sent=1 WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()

# ===================== Основные хендлеры =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот-напоминальщик.\n"
        "Напиши мне что-то вроде:\n"
        "👉 'напомни завтра в 10:00 сходить в магазин'"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    # Парсим дату и время
    remind_time = dateparser.parse(text, languages=["ru"])
    if remind_time:
        add_reminder(chat_id, text, remind_time.strftime("%Y-%m-%d %H:%M:%S"))
        await update.message.reply_text(f"✅ Напоминание сохранено: {text}")
    else:
        await update.message.reply_text("⏰ Не понял время напоминания, попробуй иначе!")

# ===================== Проверка напоминаний =====================
async def check_reminders_job(application: Application):
    reminders = get_due_reminders()
    for reminder_id, chat_id, text in reminders:
        try:
            await application.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
            mark_reminder_sent(reminder_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания: {e}")

# ===================== Планировщик =====================
def start_scheduler(application: Application):
    scheduler = BackgroundScheduler()

    def job():
        try:
            asyncio.run_coroutine_threadsafe(
                check_reminders_job(application), MAIN_LOOP
            )
        except Exception as e:
            logger.error(f"Ошибка в job: {e}")

    scheduler.add_job(job, "interval", minutes=1)
    scheduler.start()
    logger.info("🕒 Планировщик запущен")

# ===================== Запуск =====================
def main():
    global MAIN_LOOP
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Сохраняем event loop
    MAIN_LOOP = asyncio.get_event_loop()

    # Запускаем планировщик
    start_scheduler(application)

    logger.info("🚀 Запуск через Webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
