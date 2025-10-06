import os
import logging
import asyncio
from datetime import datetime
import dateparser

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --- Логирование ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Переменные окружения ---
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
PORT = int(os.getenv("PORT", 10000))

# --- Планировщик ---
jobstores = {
    "default": SQLAlchemyJobStore(url="sqlite:///jobs.sqlite")
}
scheduler = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
scheduler.start()

# --- Хэндлеры ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Я твой бот-напоминальщик.\nНапиши мне: 'напомни завтра в 10:00 сходить в магазин'")

async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Напиши текст напоминания и время!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"Получено сообщение: {text}")

    dt = dateparser.parse(text, settings={"TIMEZONE": "Asia/Almaty", "RETURN_AS_TIMEZONE_AWARE": True})
    if dt:
        job_id = f"{update.effective_chat.id}_{int(datetime.now().timestamp())}"

        scheduler.add_job(
            func=send_reminder,
            trigger="date",
            run_date=dt,
            args=[update.effective_chat.id, text],
            id=job_id,
            replace_existing=True
        )
        await update.message.reply_text(f"✅ Напоминание создано на {dt.strftime('%Y-%m-%d %H:%M')}")
    else:
        await update.message.reply_text("⚠️ Не понял время. Попробуй так: 'напомни завтра в 10:00 сходить в магазин'")

async def send_reminder(chat_id: int, text: str):
    """Функция для выполнения напоминания"""
    try:
        await application.bot.send_message(chat_id, f"🔔 Напоминание: {text}")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания: {e}")

# --- Основной запуск ---
application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("new", new))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

async def main():
    logger.info("🚀 Запуск бота через Webhook...")
    await application.bot.set_webhook(url=WEBHOOK_URL)

    await application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
