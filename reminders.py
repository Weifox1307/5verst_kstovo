import os
import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode

# Конфиг
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ORGS_CHAT_ID = os.getenv("ORGS_CHAT_ID") # ID чата организаторов

# Тексты напоминалок
REMINDERS = {
    "sunday": "📹 <b>Воскресенье:</b> Пора записать и выложить видео организатора в ТГ и ВК!",
    "tuesday": "🙋‍♂️ <b>Вторник:</b> Время для поста-зазыва волонтеров и объявления тематики старта!",
    "thursday": "✅ <b>Четверг:</b> Постим о готовности старта (разметка, инвентарь, команда)!",
    "saturday_evening": "📊 <b>Суббота вечер:</b> Не забудьте подвести итоги недели в ТГ!"
}

async def send_reminder(day_key):
    if not TOKEN or not ORGS_CHAT_ID:
        logging.error("Секреты TOKEN или ORGS_CHAT_ID не настроены!")
        return

    text = REMINDERS.get(day_key)
    if not text:
        return

    bot = Bot(token=TOKEN)
    async with bot:
        try:
            await bot.send_message(chat_id=int(ORGS_CHAT_ID), text=text, parse_mode=ParseMode.HTML)
            logging.info(f"Напоминалка {day_key} отправлена.")
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        asyncio.run(send_reminder(sys.argv[1]))
