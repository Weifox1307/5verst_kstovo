import os
import asyncio
import logging
import pytz
from datetime import datetime, timedelta
from telegram import Bot
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- ДАННЫЕ ДЛЯ РАСЧЕТА ---
# Точка отсчета: 35-й старт был 28.02.2026
START_NUMBER_BASE = 35
START_DATE_BASE = datetime(2026, 2, 28).date()

def get_ordinal_ru(n):
    """Превращает число в строку типа 'ТРИДЦАТЬ ПЯТЫЙ'"""
    units = ["", "ПЕРВЫЙ", "ВТОРОЙ", "ТРЕТИЙ", "ЧЕТВЕРТЫЙ", "ПЯТЫЙ", "ШЕСТОЙ", "СЕДЬМОЙ", "ВОСЬМОЙ", "ДЕВЯТЫЙ"]
    teens = ["ДЕСЯТЫЙ", "ОДИННАДЦАТЫЙ", "ДВЕНАДЦАТЫЙ", "ТРИНАДЦАТЫЙ", "ЧЕТЫРНАДЦАТЫЙ", "ПЯТНАДЦАТЫЙ", "ШЕСТНАДЦАТЫЙ", "СЕМНАДЦАТЫЙ", "ВОСЕМНАДЦАТЫЙ", "ДЕВЯТНАДЦАТЫЙ"]
    tens = ["", "", "ДВАДЦАТЬ", "ТРИДЦАТЬ", "СОРОК", "ПЯТЬДЕСЯТ", "ШЕСТЬДЕСЯТ", "СЕМЬДЕСЯТ", "ВОСЕМЬДЕСЯТ", "ДЕВЯНОСТО"]
    tens_ordinal = ["", "ДЕСЯТЫЙ", "ДВАДЦАТЫЙ", "ТРИДЦАТЫЙ", "СОРОКОВОЙ", "ПЯТИДЕСЯТЫЙ", "ШЕСТИДЕСЯТЫЙ", "СЕМИДЕСЯТЫЙ", "ВОСЬМИДЕСЯТЫЙ", "ДЕВЯНОСТЫЙ"]

    if n % 100 == 0: return str(n)
    
    if 10 <= n % 100 <= 19:
        return teens[n % 10]
    
    unit_part = n % 10
    ten_part = (n // 10) % 10
    
    if unit_part == 0:
        return tens_ordinal[ten_part]
    else:
        prefix = tens[ten_part] + " " if ten_part > 0 else ""
        return prefix + units[unit_part]

def get_russian_month(month_id):
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    return months.get(month_id)

async def post_volunteers_template():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
    THREAD_ID_VOL_ENV = os.getenv("THREAD_ID_VOLUNTEERS")
    VOL_THREAD = int(THREAD_ID_VOL_ENV) if THREAD_ID_VOL_ENV and THREAD_ID_VOL_ENV.strip() else None

    # Расчет даты ближайшей субботы (относительно текущего времени)
    tz = pytz.timezone("Europe/Moscow")
    now_dt = datetime.now(tz)
    days_until_saturday = (5 - now_dt.weekday()) % 7
    next_saturday = now_dt.date() + timedelta(days=days_until_saturday)
    
    # Расчет номера старта
    weeks_passed = (next_saturday - START_DATE_BASE).days // 7
    current_start_number = START_NUMBER_BASE + weeks_passed
    
    start_num_str = get_ordinal_ru(current_start_number)
    date_str = f"{next_saturday.day} {get_russian_month(next_saturday.month)} {next_saturday.year}"

    text = (
        f"<b>{date_str} - наш {start_num_str} старт! 🎉🥳🌟</b>\n"
        "08-45 парк Юбилейный (56.161129, 44.218249)\n\n"
        "Разыскиваются волонтеры для организации старта! 💪💪💪\n"
        "Что нужно будет делать расскажу, получится у каждого ⭐️\n\n"
        "Копируй сообщение, вписывай себя, меняй ➖ на ⭐️ и отправляй снова в чат.\n"
        "Или напиши мне, я помогу ➡️ @DmitryKochin / ➡️ @begKstovo\n\n"
        "ПРИМЕР: ➖ Организатор, брифинг — --------------> ⭐️Организатор, брифинг — @DmitryKochin\n\n"
        "📜Инструкции для волонтеров здесь\n"
        "👉 https://t.me/verst5kstovoyubileyniy/3479\n\n"
        "❗️Правила 5 вёрст здесь\n"
        "👉 https://t.me/verst5kstovoyubileyniy/3494\n\n"
        "Если это твое первое волонтерство, укажи свой ИД с 5 вёрст (https://clck.ru/3MdLsE) рядом со своим ником и твоя карма начнет расти 🚀\n\n"
        "➖ Организатор, брифинг — \n"
        "➖ Разметка трассы 1 — \n"
        "➖ Разметка трассы 2 — \n"
        "➖ Инструктаж новых участников — \n"
        "➖ Секундомер 1 — \n"
        "➖ Секундомер 2 — \n"
        "➖ Карточки позиций — \n"
        "➖ Сканер — \n"
        "➖ Замыкающий — \n"
        "➖ Маршал (местоположение маршала: 56.160143, 44.220195) — \n"
        "➖ Разминка — \n"
        "➖ Оборудование — \n"
        "➖ Обработка результатов (NRMS) — \n"
        "➖ Соц. Сети — \n"
        "➖ Фото — \n"
        "➖ Видео — \n"
        "➖ Вкусняшки, чай — \n"
        "———\n"
        "➖ Пейсмейкер 1 (темп) — \n"
        "➖ Пейсмейкер 2 (темп) — \n"
        "➖ Пейсмейкер 3 (темп) — \n\n"
        "Спасибо за поддержку 🫶🏻\n"
        "Наша трасса: https://www.google.com/maps/d/u/0/edit?mid=1keRSqOyRwOKILaXdomR4TLh5TwwinF0&usp=sharing\n"
        "Группа вк: https://vk.ru/5verstkstovoyubileyniy\n"
        "Наш сайт: https://5verst.ru/kstovoyubileyniy\n"
        "#наборволонтеров\n\n"
        "Поддержать 5 вёрст Кстово можно по ссылке 👉 https://5verst.ru/forever/kstovoyubileyniy/"
    )

    if not TOKEN or not TARGET_CHAT_ID:
        logger.error("Ошибка: Не настроены TOKEN или TARGET_CHAT_ID!")
        return

    try:
        bot = Bot(token=TOKEN)
        async with bot:
            await bot.send_message(
                chat_id=int(TARGET_CHAT_ID),
                text=text,
                parse_mode=ParseMode.HTML,
                message_thread_id=VOL_THREAD,
                disable_web_page_preview=True
            )
            logger.info(f"Сообщение на {date_str} (старт {current_start_number}) отправлено.")
    except Exception as e:
        logger.error(f"Ошибка при отправке: {e}")

if __name__ == "__main__":
    asyncio.run(post_volunteers_template())
