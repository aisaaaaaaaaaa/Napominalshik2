import logging
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# === Логирование ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Константы ===
SET_TEXT, SET_TIME = range(2)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN or not WEBHOOK_URL:
    raise ValueError("❌ Укажи BOT_TOKEN и WEBHOOK_URL в переменных окружения!")

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

def get_user_reminders(user_id):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, time, status FROM reminders WHERE user_id=? ORDER BY time ASC",
        (user_id,)
    )
    res = cursor.fetchall()
    conn.close()
    return res

def delete_reminder(rid, user_id):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id=? AND user_id=?", (rid, user_id))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    return changes > 0

def get_pending_reminders():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, chat_id, text FROM reminders WHERE time <= ? AND status = 'active'",
        (now,)
    )
    res = cursor.fetchall()
    conn.close()
    return res

def mark_reminder_sent(rid):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status='sent' WHERE id=?", (rid,))
    conn.commit()
    conn.close()

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["📝 Новое"], ["📋 Мои напоминания"], ["❌ Отмена"]]
    await update.message.reply_text(
        "👋 Привет! Я — твой бот-напоминальщик.\n"
        "Используй меню или команды:\n"
        "/new — создать напоминание\n"
        "/list — список\n"
        "/delete — удалить\n"
        "/help — помощь",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Доступные команды:\n"
        "/start — запуск\n"
        "/new — создать новое напоминание\n"
        "/list — показать список\n"
        "/delete <id> — удалить\n"
        "/cancel — отмена\n"
    )

# === Создание напоминания ===
async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи текст напоминания:", reply_markup=ReplyKeyboardRemove())
    return SET_TEXT

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["text"] = update.message.text
    await update.message.reply_text("⏰ Введи время (минуты или ГГГГ-ММ-ДД ЧЧ:ММ):")
    return SET_TIME

async def save_reminder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = context.user_data["text"]
    time_input = update.message.text.strip()

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

        rid = save_reminder(user_id, chat_id, text, time_str)
        await update.message.reply_text(f"✅ Напоминание #{rid} создано на {time_str}")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Неверный формат времени")
        return SET_TIME

# === Список напоминаний ===
async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = get_user_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("📭 У тебя нет активных напоминаний")
        return

    msg = "📋 Твои напоминания:\n"
    for rid, text, time, status in reminders:
        msg += f"#{rid} — {text} ⏰ {time} [{status}]\n"
    await update.message.reply_text(msg)

# === Удаление ===
async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Используй: /delete <id>")
        return

    rid = context.args[0]
    if rid.isdigit():
        success = delete_reminder(int(rid), update.effective_user.id)
        if success:
            await update.message.reply_text(f"🗑 Напоминание #{rid} удалено")
        else:
            await update.message.reply_text("❌ Не найдено")
    else:
        await update.message.reply_text("❌ ID должен быть числом")

# === Отмена ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Отменено", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# === Проверка напоминаний ===
async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    pending = get_pending_reminders()
    for rid, chat_id, text in pending:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
            mark_reminder_sent(rid)
        except Exception as e:
            logger.error(f"Ошибка при отправке {rid}: {e}")

# === Запуск ===
if __name__ == "__main__":
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_reminders))
    app.add_handler(CommandHandler("delete", delete_command))

    conv = ConversationHandler(
        entry_points=[CommandHandler("new", new_reminder)],
        states={
            SET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_time)],
            SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # Проверка каждую минуту
    app.job_queue.run_repeating(check_reminders_job, interval=60, first=10)

    logger.info("🚀 Запуск webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )
