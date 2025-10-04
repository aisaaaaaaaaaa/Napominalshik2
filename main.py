import logging
import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы состояний
SET_REMINDER, SET_TIME = range(2)

# Инициализация Flask
app = Flask(__name__)

# Получение токена и URL из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не установлена")
if not WEBHOOK_URL:
    raise ValueError("❌ Переменная WEBHOOK_URL не установлена")

# Создание Application
application = Application.builder().token(BOT_TOKEN).build()

# === Работа с базой данных ===

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
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def save_reminder(user_id: int, chat_id: int, text: str, time: str):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reminders (user_id, chat_id, text, time) VALUES (?, ?, ?, ?)",
        (user_id, chat_id, text, time)
    )
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"💾 Сохранено напоминание {reminder_id} для {user_id}: {text} в {time}")
    return reminder_id

def get_user_reminders(user_id: int):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, time, status FROM reminders WHERE user_id = ? AND status = 'active' ORDER BY time",
        (user_id,)
    )
    reminders = cursor.fetchall()
    conn.close()
    return reminders

def get_pending_reminders():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, chat_id, text FROM reminders WHERE time <= ? AND status = 'active'",
        (now,)
    )
    reminders = cursor.fetchall()
    conn.close()
    return reminders

def mark_reminder_sent(reminder_id: int):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    logger.info(f"✅ Напоминание {reminder_id} помечено как отправленное")

# === Обработчики команд ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📩 Получена команда /start от {update.effective_user.id}")
    keyboard = [["📝 Создать напоминание", "📋 Мои напоминания"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Привет! Я бот-напоминальщик.\n\n"
        "Создавайте напоминания, и я пришлю уведомление в указанное время.",
        reply_markup=reply_markup
    )

async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введите текст напоминания:", reply_markup=ReplyKeyboardRemove())
    return SET_REMINDER

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reminder_text"] = update.message.text
    await update.message.reply_text(
        "⏰ Введите время в формате:\n"
        "• ГГГГ-ММ-ДД ЧЧ:ММ (например: 2024-12-31 23:59)\n"
        "• Или через сколько минут (например: 30)"
    )
    return SET_TIME

async def save_reminder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_input = update.message.text.strip()
    reminder_text = context.user_data["reminder_text"]

    try:
        if time_input.isdigit():
            minutes = int(time_input)
            reminder_time = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
            time_display = f"через {minutes} минут"
        else:
            reminder_time_obj = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            if reminder_time_obj <= datetime.now():
                await update.message.reply_text("❌ Время должно быть в будущем!")
                return SET_TIME
            reminder_time = time_input
            time_display = reminder_time

        reminder_id = save_reminder(
            update.effective_user.id,
            update.effective_chat.id,
            reminder_text,
            reminder_time
        )

        keyboard = [["📝 Создать напоминание", "📋 Мои напоминания"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"✅ Напоминание создано! (ID: {reminder_id})\n\n"
            f"📝 Текст: {reminder_text}\n"
            f"⏰ Время: {time_display}",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени!\n"
            "Используйте:\n"
            "• ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "• Или количество минут"
        )
        return SET_TIME

async def show_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = get_user_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("📭 У вас нет активных напоминаний")
        return
    text = "📋 Ваши напоминания:\n\n"
    for reminder_id, reminder_text, reminder_time, _ in reminders:
        text += f"⏳ ID:{reminder_id}\n   📝 {reminder_text}\n   ⏰ {reminder_time}\n\n"
    text += "Для удаления используйте /delete ID"
    await update.message.reply_text(text)

async def delete_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите ID напоминания\nПример: /delete 1")
        return
    try:
        reminder_id = int(context.args[0])
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, update.effective_user.id))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Напоминание #{reminder_id} удалено" if deleted else "❌ Не найдено")
    except ValueError:
        await update.message.reply_text("❌ Неверный ID")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🤖 **Команды бота:**
/new — создать напоминание  
/my_reminders — мои напоминания  
/delete [ID] — удалить напоминание  
/help — помощь
    """)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📝 Создать напоминание", "📋 Мои напоминания"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("❌ Действие отменено", reply_markup=reply_markup)
    return ConversationHandler.END

# === Настройка обработчиков ===
def setup_handlers():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("my_reminders", show_reminders))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete", delete_reminder_command))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("new", set_reminder),
            MessageHandler(filters.Regex("^📝 Создать напоминание$"), set_reminder)
        ],
        states={
            SET_REMINDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_time)],
            SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^📋 Мои напоминания$"), show_reminders))

# === Flask эндпоинты ===

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    application.update_queue.put_nowait(
        Update.de_json(request.get_json(force=True), application.bot)
    )
    return "OK"

@app.route("/check", methods=["GET"])
def check_reminders():
    try:
        pending = get_pending_reminders()
        logger.info(f"🔍 Найдено {len(pending)} напоминаний для отправки")
        for reminder_id, chat_id, text in pending:
            try:
                application.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
                mark_reminder_sent(reminder_id)
                logger.info(f"📤 Отправлено напоминание {reminder_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки {reminder_id}: {e}")
        return {"status": "ok", "sent": len(pending)}
    except Exception as e:
        logger.error(f"🔥 Ошибка в /check: {e}")
        return {"status": "error", "message": str(e)}, 500

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Bot is running (webhook mode)."

# === Запуск приложения ===
if __name__ == "__main__":
    init_db()
    setup_handlers()

    # Критически важно: инициализировать Application для webhook
    import asyncio
    async def start_bot():
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"🔗 Webhook установлен на {WEBHOOK_URL}")

    asyncio.run(start_bot())

    # Запуск Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
