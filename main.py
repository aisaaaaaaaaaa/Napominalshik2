import logging
import os
import sqlite3
from datetime import datetime, timedelta
import asyncio

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
SET_REMINDER, SET_TIME = range(2)

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://napominalshik2.onrender.com/webhook")
PORT = int(os.getenv("PORT", 10000))

# === База данных ===
def init_db():
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            text TEXT,
            time TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()

def save_reminder(user_id, chat_id, text, time):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reminders (user_id, chat_id, text, time) VALUES (?, ?, ?, ?)",
        (user_id, chat_id, text, time)
    )
    rid = cursor.lastrowid
    conn.commit()
    conn.close()
    return rid

def get_pending_reminders():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, text FROM reminders WHERE time <= ? AND status = 'active'", (now,))
    res = cursor.fetchall()
    conn.close()
    return res

def mark_reminder_sent(rid):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

# === Обработчики ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["📝 Создать напоминание"]]
    await update.message.reply_text("👋 Привет! Я твой напоминальщик.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи текст напоминания:", reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True))
    return SET_REMINDER

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["text"] = update.message.text
    await update.message.reply_text("⏰ Введи время (например `10` для минут или `2025-10-06 14:30`):")
    return SET_TIME

async def save_reminder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_input = update.message.text.strip()
    text = context.user_data["text"]
    try:
        if time_input.isdigit():
            minutes = int(time_input)
            time_str = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        else:
            time_obj = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            if time_obj <= datetime.now():
                await update.message.reply_text("❌ Время в прошлом!")
                return SET_TIME
            time_str = time_input

        rid = save_reminder(update.effective_user.id, update.effective_chat.id, text, time_str)
        await update.message.reply_text(f"✅ Напоминание #{rid} создано!")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Неверный формат времени, попробуй ещё раз")
        return SET_TIME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Создание напоминания отменено.")
    return ConversationHandler.END

# === Проверка напоминаний ===
async def check_reminders_job(application: Application):
    pending = get_pending_reminders()
    for rid, chat_id, text in pending:
        try:
            await application.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
            mark_reminder_sent(rid)
        except Exception as e:
            logger.error(f"Ошибка отправки {rid}: {e}")

def start_scheduler(application: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.create_task(check_reminders_job(application)),
        trigger=IntervalTrigger(minutes=1)
    )
    scheduler.start()

# === Запуск ===
if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Обработчики
    app.add_handler(CommandHandler("start", start))
    conv = ConversationHandler(
        entry_points=[CommandHandler("new", set_reminder)],
        states={
            SET_REMINDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_time)],
            SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv)

    # Запускаем планировщик
    start_scheduler(app)

    # Запуск webhook
    logger.info("🚀 Запуск через Webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )
