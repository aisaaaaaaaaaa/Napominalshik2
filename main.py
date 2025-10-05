import os
import logging
import asyncio
from datetime import datetime

import dateparser
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

# ==============================
# ЛОГИ
# ==============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# ХРАНИЛИЩЕ НАПОМИНАНИЙ (в памяти)
# ==============================
reminders = {}  # {chat_id: [(time, text)]}


# ==============================
# КОМАНДЫ
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот-напоминальщик.\n"
        "Напиши что-то вроде:\n\n"
        "👉 напомни завтра в 10:00 сходить в магазин\n"
        "👉 напомни через 5 минут проверить чайник"
    )


async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✍ Введи напоминание в формате: напомни [время] [текст]")


# ==============================
# ДОБАВЛЕНИЕ НАПОМИНАНИЯ
# ==============================
async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.lower()

    if not text.startswith("напомни"):
        return

    # убираем слово "напомни"
    reminder_text = text.replace("напомни", "", 1).strip()

    # парсим время
    reminder_time = dateparser.parse(reminder_text, languages=["ru"], settings={"PREFER_DATES_FROM": "future"})

    if not reminder_time:
        await update.message.reply_text("⚠ Не понял время. Попробуй так: 'напомни завтра в 10:00 купить хлеб'.")
        return

    # убираем время из текста напоминания
    clean_text = reminder_text.replace(str(reminder_time.date()), "").strip()

    reminders.setdefault(chat_id, []).append((reminder_time, clean_text))

    await update.message.reply_text(
        f"✅ Напоминание создано!\n"
        f"🕒 Когда: {reminder_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"📌 Что: {clean_text}"
    )
    logger.info(f"Создано напоминание для {chat_id}: {reminder_time} -> {clean_text}")


# ==============================
# ПРОВЕРКА НАПОМИНАНИЙ
# ==============================
async def check_reminders_job(application: Application):
    now = datetime.now()
    for chat_id, user_reminders in list(reminders.items()):
        for reminder_time, text in user_reminders[:]:
            if reminder_time <= now:
                try:
                    await application.bot.send_message(chat_id=chat_id, text=f"⏰ Напоминание: {text}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке напоминания: {e}")
                user_reminders.remove((reminder_time, text))


# ==============================
# ЗАПУСК ПЛАНИРОВЩИКА
# ==============================
def start_scheduler(application: Application):
    scheduler = BackgroundScheduler()

    # теперь используем application.create_task вместо asyncio.create_task
    def job():
        application.create_task(check_reminders_job(application))

    scheduler.add_job(job, trigger=IntervalTrigger(minutes=1))
    scheduler.start()
    logger.info("🕒 Планировщик запущен")


# ==============================
# MAIN
# ==============================
def main():
    TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
    PORT = int(os.getenv("PORT", 10000))

    application = Application.builder().token(TOKEN).build()

    # команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new", new))

    # обработка текста
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder))

    # запускаем планировщик
    start_scheduler(application)

    # запуск через webhook (Render)
    logger.info("🚀 Запуск через Webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="/webhook",
        webhook_url=WEBHOOK_URL
    )


if __name__ == "__main__":
    main()
