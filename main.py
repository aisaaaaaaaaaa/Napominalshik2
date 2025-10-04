import logging
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    JobQueue,
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы состояний для ConversationHandler
SET_REMINDER, SET_TIME = range(2)


class ReminderBot:
    def __init__(self, token: str):
        self.token = token
        self.application = ApplicationBuilder().token(token).build()
        self.init_db()
        self.setup_handlers()

    def init_db(self):
        """Инициализация базы данных"""
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
        logger.info("База данных инициализирована")

    def save_reminder(self, user_id: int, chat_id: int, text: str, time: str):
        """Сохранение напоминания в БД"""
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (user_id, chat_id, text, time) VALUES (?, ?, ?, ?)",
            (user_id, chat_id, text, time)
        )
        reminder_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Сохранено напоминание {reminder_id} для user {user_id}: {text} в {time}")
        return reminder_id

    def get_user_reminders(self, user_id: int):
        """Получение напоминаний пользователя"""
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text, time, status FROM reminders WHERE user_id = ? AND status = 'active' ORDER BY time",
            (user_id,)
        )
        reminders = cursor.fetchall()
        conn.close()
        return reminders

    def get_pending_reminders(self):
        """Получение напоминаний готовых к отправке"""
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

    def mark_reminder_sent(self, reminder_id: int):
        """Пометить напоминание как отправленное"""
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reminders SET status = 'sent' WHERE id = ?",
            (reminder_id,)
        )
        conn.commit()
        conn.close()
        logger.info(f"Напоминание {reminder_id} помечено как отправленное")

    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("my_reminders", self.show_reminders))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("debug", self.debug_info))
        self.application.add_handler(CommandHandler("test", self.test_reminder))

        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("new", self.set_reminder),
                MessageHandler(filters.Regex("^📝 Создать напоминание$"), self.set_reminder)
            ],
            states={
                SET_REMINDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_time)],
                SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_reminder_handler)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        self.application.add_handler(conv_handler)

        self.application.add_handler(
            MessageHandler(filters.Regex("^📋 Мои напоминания$"), self.show_reminders)
        )

        self.application.add_handler(CommandHandler("delete", self.delete_reminder_command))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [["📝 Создать напоминание", "📋 Мои напоминания"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "👋 Привет! Я бот-напоминальщик.\n\n"
            "Создавайте напоминания, и я пришлю уведомление в указанное время.",
            reply_markup=reply_markup
        )

    async def debug_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для отладки"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = sqlite3.connect("reminders.db", check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM reminders")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'active'")
        active = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reminders WHERE status = 'sent'")
        sent = cursor.fetchone()[0]

        cursor.execute("SELECT id, text, time FROM reminders WHERE status = 'active' ORDER BY time LIMIT 5")
        next_reminders = cursor.fetchall()

        conn.close()

        debug_text = f"""
🔧 **Информация для отладки:**

⏰ Текущее время: `{now}`
📊 Всего напоминаний: `{total}`
🟢 Активных: `{active}`
✅ Отправленных: `{sent}`

**Ближайшие напоминания:**
"""
        for i, (rem_id, text, time) in enumerate(next_reminders, 1):
            debug_text += f"{i}. ID:{rem_id} `{time}` - {text}\n"

        await update.message.reply_text(debug_text, parse_mode='Markdown')

    async def test_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестовая команда - создает напоминание на 1 минуту вперед"""
        test_time = (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        reminder_id = self.save_reminder(
            update.effective_user.id,
            update.effective_chat.id,
            "ТЕСТОВОЕ напоминание",
            test_time
        )

        await update.message.reply_text(
            f"🧪 Создано тестовое напоминание!\n"
            f"ID: {reminder_id}\n"
            f"Время: {test_time}\n\n"
            f"Ждите уведомление через 1 минуту!"
        )

    async def set_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📝 Введите текст напоминания:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SET_REMINDER

    async def set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["reminder_text"] = update.message.text
        await update.message.reply_text(
            "⏰ Введите время в формате:\n"
            "• ГГГГ-ММ-ДД ЧЧ:ММ (например: 2024-12-31 23:59)\n"
            "• Или через сколько минут (например: 30)\n\n"
            "Примеры:\n"
            "• 2024-12-31 23:59\n"
            "• 30 (через 30 минут)"
        )
        return SET_TIME

    async def save_reminder_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

            reminder_id = self.save_reminder(
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

    async def show_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        reminders = self.get_user_reminders(update.effective_user.id)

        if not reminders:
            await update.message.reply_text("📭 У вас нет активных напоминаний")
            return

        text = "📋 Ваши напоминания:\n\n"
        for reminder_id, reminder_text, reminder_time, status in reminders:
            status_icon = "⏳"
            text += f"{status_icon} ID:{reminder_id}\n   📝 {reminder_text}\n   ⏰ {reminder_time}\n\n"

        text += "Для удаления используйте /delete ID"
        await update.message.reply_text(text)

    async def delete_reminder_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("❌ Укажите ID напоминания для удаления\nПример: /delete 1")
            return

        try:
            reminder_id = int(context.args[0])
            conn = sqlite3.connect("reminders.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, update.effective_user.id)
            )
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()

            if deleted:
                await update.message.reply_text(f"✅ Напоминание #{reminder_id} удалено")
            else:
                await update.message.reply_text("❌ Напоминание не найдено")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID напоминания")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
🤖 **Команды бота:**
/new - создать напоминание
/my_reminders - мои напоминания  
/delete [ID] - удалить напоминание
/debug - информация для отладки
/test - создать тестовое напоминание (через 1 минуту)
/help - помощь
        """
        await update.message.reply_text(help_text)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [["📝 Создать напоминание", "📋 Мои напоминания"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("❌ Действие отменено", reply_markup=reply_markup)
        return ConversationHandler.END

    async def check_reminders_job(self, context: ContextTypes.DEFAULT_TYPE):
        """Периодическая проверка напоминаний"""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            logger.info(f"🔍 Проверка напоминаний в {now}")

            reminders = self.get_pending_reminders()
            logger.info(f"📤 Найдено напоминаний для отправки: {len(reminders)}")

            for reminder_id, chat_id, text in reminders:
                logger.info(f"  Отправляю напоминание {reminder_id} в чат {chat_id}")

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔔 Напоминание: {text}"
                    )
                    self.mark_reminder_sent(reminder_id)
                    logger.info(f"✅ Успешно отправлено напоминание {reminder_id}")

                except Exception as e:
                    logger.error(f"❌ Ошибка отправки напоминания {reminder_id}: {e}")

        except Exception as e:
            logger.error(f"🔥 Ошибка в check_reminders_job: {e}")

    def run(self):
        """Запуск бота"""
        # Добавляем периодическую задачу для проверки напоминаний
        job_queue = self.application.job_queue
        job_queue.run_repeating(self.check_reminders_job, interval=30, first=10)

        logger.info("Бот запущен с JobQueue...")
        self.application.run_polling()


def main():
    BOT_TOKEN = "7309853259:AAEgnNjHnRLBWMt-0K6VRkJTXIczj2HvPd0"

    bot = ReminderBot(BOT_TOKEN)
    bot.run()


if __name__ == "__main__":
    main()
