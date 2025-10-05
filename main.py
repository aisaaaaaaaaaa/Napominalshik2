import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен из переменных окружения Render (Environment → Environment Variables)
TOKEN = os.getenv("BOT_TOKEN")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Я напоминальщик. Используй /new чтобы создать напоминание.")

# Команда /new
async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✍️ Напиши, что и когда тебе напомнить.")

async def main():
    # Создаём приложение
    app = Application.builder().token(TOKEN).build()

    # Добавляем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new))

    # URL твоего приложения на Render
    webhook_url = "https://napominalshik2.onrender.com"

    # Настраиваем вебхук
    await app.bot.set_webhook(webhook_url)

    # Запускаем приложение (получает апдейты через вебхук)
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),  # Render задаёт PORT автоматически
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
