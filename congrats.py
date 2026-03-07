import os
import asyncio
from telegram import Bot
from telegram.constants import ParseMode

# Данные берутся из секретов GitHub
TOKEN = os.getenv("TOKEN")
CHAT_IDS = os.getenv("TARGET_CHAT_IDS", "").split(",") 
THREAD_ID = os.getenv("THREAD_ID") 

async def send_congrats():
    if not TOKEN or not CHAT_IDS:
        print("Ошибка: TOKEN или TARGET_CHAT_IDS не найдены.")
        return

    bot = Bot(token=TOKEN)
    
    # Лаконичный и точный текст без лишних слов
    text = (
        "🌷 <b>С Праздником 8 марта!</b> 🌷\n\n"
        "Дорогие наши девушки — участницы, волонтёры и организаторы! "
        "Вы — душа и энергия наших субботних стартов. Именно ваши улыбки "
        "делают каждое утро в парке по-настоящему добрым и вдохновляющим. ✨\n\n"
        "Желаем вам весеннего настроения, лёгких километров и ярких личных рекордов. "
        "Пусть каждый старт приносит только радость и заряд бодрости на всю неделю! 🏃‍♀️🌸\n\n"
        "С любовью, команда 5 вёрст в парке Юбилейный | Кстово !🧡"
    )

    async with bot:
        for chat_id in CHAT_IDS:
            clean_id = chat_id.strip()
            if not clean_id:
                continue
            try:
                await bot.send_message(
                    chat_id=int(clean_id),
                    text=text,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=int(THREAD_ID) if THREAD_ID else None
                )
                print(f"Поздравление отправлено в чат {clean_id}")
            except Exception as e:
                print(f"Ошибка при отправке в {clean_id}: {e}")

if __name__ == "__main__":
    asyncio.run(send_congrats())
