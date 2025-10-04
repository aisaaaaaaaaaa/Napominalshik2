import logging
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
SET_REMINDER, SET_TIME = range(2)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен")
if not WEBHOOK_URL:
    raise ValueError("❌ WEBHOOK_URL не установлен")

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
    rid = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"💾 Напоминание {rid} сохранено")
    return rid

def get_user_reminders(user_id: int):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, time, status FROM reminders WHERE user_id = ? AND status = 'active' ORDER BY time",
        (user_id,)
    )
    res = cursor.fetchall()
    conn.close()
    return res

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

def mark_reminder_sent(rid: int):
    conn = sqlite3.connect("reminders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    logger.info(f"✅ Напоминание {rid} отправлено")

# === Обработчики ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📩 /start от {update.effective_user.id}")
    kb = [["📝 Создать напоминание", "📋 Мои напоминания"]]
    await update.message.reply_text(
        "👋 Привет! Я бот-напоминальщик.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def set_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Текст напоминания:", reply_markup=ReplyKeyboardRemove())
    return SET_REMINDER

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["text"] = update.message.text
    await update.message.reply_text("⏰ Время (ГГГГ-ММ-ДД ЧЧ:ММ или минуты):")
    return SET_TIME

async def save_reminder_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_input = update.message.text.strip()
    text = context.user_data["text"]
    try:
        if time_input.isdigit():
            minutes = int(time_input)
            time_str = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
            display = f"через {minutes} мин"
        else:
            time_obj = datetime.strptime(time_input, "%Y-%m-%d %H:%M")
            if time_obj <= datetime.now():
                await update.message.reply_text("❌ Время в прошлом!")
                return SET_TIME
            time_str = time_input
            display = time_str

        rid = save_reminder(update.effective_user.id, update.effective_chat.id, text, time_str)
        kb = [["📝 Создать напоминание", "📋 Мои напоминания"]]
        await update.message.reply_text(
            f"✅ Напоминание #{rid}\n📝 {text}\n⏰ {display}",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат времени")
        return SET_TIME

async def show_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rem = get_user_reminders(update.effective_user.id)
    if not rem:
        await update.message.reply_text("📭 Нет напоминаний")
        return
    msg = "📋 Ваши напоминания:\n\n"
    for rid, text, time, _ in rem:
        msg += f"⏳ ID:{rid}\n   📝 {text}\n   ⏰ {time}\n\n"
    msg += "Удалить: /delete ID"
    await update.message.reply_text(msg)

async def delete_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ /delete <ID>")
        return
    try:
        rid = int(context.args[0])
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (rid, update.effective_user.id))
        ok = c.rowcount > 0
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Удалено" if ok else "❌ Не найдено")
    except ValueError:
        await update.message.reply_text("❌ Неверный ID")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Команды: /new, /my_reminders, /delete <ID>")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["📝 Создать напоминание", "📋 Мои напоминания"]]
    await update.message.reply_text("❌ Отменено", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ConversationHandler.END

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Вызывается по расписанию через /check (вручную)"""
    pending = get_pending_reminders()
    logger.info(f"🔍 Найдено {len(pending)} напоминаний")
    for rid, chat_id, text in pending:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"🔔 Напоминание: {text}")
            mark_reminder_sent(rid)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {rid}: {e}")

# === Webhook эндпоинт для /check ===
from aiohttp import web

async def handle_check(request):
    """Эндпоинт для cron-job.org"""
    try:
        # Имитируем вызов JobQueue
        from telegram.ext import ContextTypes
        from types import SimpleNamespace
        fake_update = SimpleNamespace()
        fake_context = ContextTypes.DEFAULT_TYPE(bot=application.bot)
        await check_reminders(fake_context)
        return web.json_response({"status": "ok", "sent": "checked"})
    except Exception as e:
        logger.error(f"🔥 Ошибка в /check: {e}")
        return web.json_response({"status": "error", "msg": str(e)}, status=500)

# === Запуск ===
if __name__ == "__main__":
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("my_reminders", show_reminders))
    application.add_handler(CommandHandler("delete", delete_reminder_command))

    conv = ConversationHandler(
        entry_points=[CommandHandler("new", set_reminder)],
        states={
            SET_REMINDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_time)],
            SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(conv)

    # Запуск webhook
    logger.info("🚀 Запуск webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,  # секретный путь для безопасности
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )
