import os
import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackContext
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz

# 🔹 Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🔹 Конфиг
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com")
PORT = int(os.getenv("PORT", "8080"))

# 🔹 База данных пока простая (в памяти)
reminders = {}

# --- Команды бота ---
async def start(update, context: CallbackContext):
    await update.message.reply_text("Привет 👋! Я бот-напоминальщик. Используй /new чтобы создать напоминание.")

async def new_reminder(update, context: CallbackContext):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /new <HH:MM> <текст>")
        return
    
    time_str = context.args[0]
    text = " ".join(context.args[1:])
    user_id = update.effective_user.id

    if user_id not in reminders:
        reminders[user_id] = []

    reminders[user_id].append((time_str, text))
    await update.message.reply_text(f"✅ Напоминание добавлено: {time_str} — {text}")

async def list_reminders(update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in reminders or not reminders[user_id]:
        await update.message.reply_text("У тебя пока нет напоминаний.")
        return

    msg = "⏰ Твои напоминания:\n"
    for t, txt in reminders[user_id]:
        msg += f"• {t} — {txt}\n"
    await update.message.reply_text(msg)

# --- Планировщик ---
def check_reminders_job(app: Application):
    now = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%H:%M")
    for user_id, user_reminders in reminders.items():
        for t, txt in user_reminders:
            if t == now:
                app.bot.send_message(chat_id=user_id, text=f"🔔 Напоминание: {txt}")

# --- Основной запуск ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_reminder))
    app.add_handler(CommandHandler("list", list_reminders))

    # Планировщик
    scheduler = BackgroundScheduler(timezone="Asia/Almaty")
    scheduler.add_job(lambda: check_reminders_job(app), "interval", minutes=1)
    scheduler.start()

    # 🚀 Запуск
    if os.getenv("RENDER") == "true":  
        # для Render → запускаем Webhook
        logger.info("🚀 Запуск через Webhook...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        # локально → polling
        logger.info("🚀 Запуск через Polling...")
        app.run_polling()

if __name__ == "__main__":
    main()
