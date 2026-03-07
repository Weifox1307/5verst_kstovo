import os
import asyncio
from telegram import Bot
from telegram.constants import ParseMode

# Данные берутся из секретов GitHub (БЕЗ буквы S на конце)
TOKEN = os.getenv("TOKEN")
# Читаем как одну строку, на случай если там один ID или несколько через запятую
RAW_CHAT_ID = os.getenv("TARGET_CHAT_ID") 
THREAD_ID = os.getenv("THREAD_ID") 

async def send_congrats():
    # Проверка наличия данных
    if not TOKEN or not RAW_CHAT_ID:
        print(f"Ошибка: TOKEN или TARGET_CHAT_ID не найдены.")
        print(f"TOKEN: {'ОК' if TOKEN else 'Пусто'}")
        print(f"TARGET_CHAT_ID: {'ОК' if RAW_CHAT_ID else 'Пусто'}")
        return

    # Разбиваем по запятой, если ID несколько, и очищаем от пробелов
    chat_list = [id.strip() for id in RAW_CHAT_ID.split(",") if id.strip()]
    
    bot = Bot(token=TOKEN)
    
    text = (
        "🌷 <b>С Праздником 8 марта!</b> 🌷\n\n"
        "Дорогие наши девушки — участницы, волонтёры и организаторы! "
        "Вы — душа и энергия наших субботних стартов. Именно ваши улыбки "
        "делают каждое утро в парке по-настоящему добрым и вдохновляющим. ✨\n\n"
        "Желаем вам весеннего настроения, лёгких километров и ярких личных рекордов. "
        "Пусть каждый старт приносит только радость и заряд бодрости на всю неделю! 🏃‍♀️🌸\n\n"
        "С любовью, команда 5 вёрст в парке Юбилейный | Кстово! 🩷"
    )

    async with bot:
        for chat_id in chat_list:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=text,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=int(THREAD_ID) if THREAD_ID else None
                )
                print(f"Поздравление отправлено в чат {chat_id}")
            except Exception as e:
                print(f"Ошибка при отправке в {chat_id}: {e}")

if __name__ == "__main__":
    asyncio.run(send_congrats())
