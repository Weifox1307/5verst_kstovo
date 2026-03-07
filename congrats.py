import os
import asyncio
from telegram import Bot
from telegram.constants import ParseMode

# Данные берутся из env (которые мы прописали в yml)
TOKEN = os.getenv("TOKEN")
RAW_CHAT_ID = os.getenv("TARGET_CHAT_ID")
THREAD_ID = os.getenv("THREAD_ID")

async def send_congrats():
    if not TOKEN or not RAW_CHAT_ID:
        print(f"Ошибка: TOKEN или TARGET_CHAT_ID не найдены.")
        return

    chat_list = [id.strip() for id in RAW_CHAT_ID.split(",") if id.strip()]
    bot = Bot(token=TOKEN)
    
    # Новый уникальный текст для Станкозавода
    text = (
        "🌸 <b>С Праздником 8 марта!</b> 🌸\n\n"
        "Наши прекрасные участницы, волонтёры и организаторы! "
        "Поздравляем вас с праздником весны. Спасибо за вашу поддержку, "
        "невероятную атмосферу и тепло, которое вы приносите на каждый наш старт. ✨\n\n"
        "Желаем вам весеннего вдохновения, солнечных улыбок и лёгких финишей. "
        "Пусть каждый километр будет в удовольствие, а субботнее утро всегда "
        "заряжает отличным настроением! 🏃‍♀️🌷\n\n"
        "С любовью, команда 5 вёрст в парке Станкозавода | Нижний Новгород! 🩷"
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
