import os
import logging
import json
import asyncio
import requests
import re
import html
import pytz
import sys
from io import StringIO
from datetime import datetime
import pandas as pd
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from telegram.constants import ParseMode

# ========================= КОНФИГ =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID", "-1002607891507")
TIMEZONE = "Europe/Moscow"

NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
SHEET_BASE_URL = os.getenv("SHEET_BASE_URL")
SHEET_FORM_URL = os.getenv("SHEET_FORM_URL")
CACHE_FILE = "5verst_cache.json"

SHEET_BIRTHDAYS_URL = os.getenv("SHEET_BIRTHDAYS_URL") 
THREAD_ID_ENV = os.getenv("THREAD_ID")
THREAD_ID = int(THREAD_ID_ENV) if THREAD_ID_ENV and THREAD_ID_ENV.strip() else None

# ========================= ВСПОМОГАТЕЛЬНОЕ =========================
def extract_id(input_str):
    s = str(input_str).strip()
    if not s or s.lower() == 'nan': return None
    digits = re.sub(r"\D", "", s)
    return digits if digits else None

def login_5verst():
    try:
        r = requests.post("https://nrms.5verst.ru/api/v1/auth/login", 
                          json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        r.raise_for_status()
        token = r.json().get("result", {}).get("token")
        if token:
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        logger.error("Не удалось получить токен NRMS")
        return None
    except Exception as e:
        logger.error(f"Ошибка авторизации NRMS: {e}")
        return None

# ========================= ЛОГИКА ТИТУЛОВ =========================
async def update_titles():
    logger.info("--- СТАРТ ОБНОВЛЕНИЯ ТИТУЛОВ ---")
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {str(TARGET_CHAT_ID): {}}

    valid_chat_members = set()
    try:
        res_base = requests.get(SHEET_BASE_URL, timeout=20)
        df_base = pd.read_csv(StringIO(res_base.text))
        for _, row in df_base.iterrows():
            tg_id = extract_id(row.iloc[0])
            if tg_id: valid_chat_members.add(str(tg_id))
    except Exception as e:
        logger.error(f"Ошибка Sheet1: {e}")

    try:
        res_form = requests.get(SHEET_FORM_URL, timeout=20)
        df_form = pd.read_csv(StringIO(res_form.text))
        for _, row in df_form.iterrows():
            f_tg_id = extract_id(row.iloc[1])
            f_v5_id = extract_id(row.iloc[2])
            if f_tg_id and f_v5_id and f_tg_id in valid_chat_members:
                if str(TARGET_CHAT_ID) not in cache: cache[str(TARGET_CHAT_ID)] = {}
                cache[str(TARGET_CHAT_ID)][str(f_tg_id)] = int(f_v5_id)
    except Exception as e:
        logger.error(f"Ошибка формы: {e}")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    headers = login_5verst()
    if not headers: return

    bot = Bot(token=TOKEN)
    async with bot:
        for tg_id, v5_id in cache.get(str(TARGET_CHAT_ID), {}).items():
            try:
                r = requests.post("https://nrms.5verst.ru/api/v1/website/athlete/statById", 
                                  json={"id": v5_id}, headers=headers, timeout=15)
                stats = r.json().get("result")
                if not stats: continue

                m = stats.get("personal_best", {}).get("club_membership", {})
                run = {"run500":"500","run250":"250","run100":"100","run50":"50","run25":"25","run10":"10"}.get(m.get("run"), "")
                vol = {"vol500":"500","vol250":"250","vol100":"100","vol50":"50","vol25":"25","vol10":"10"}.get(m.get("volunteer"), "")
                badges = [b for b in [run, vol] if b]
                title = f"Клуб {'|'.join(badges)}" if badges else "Новичок"

                uid = int(tg_id)
                try:
                    await bot.promote_chat_member(chat_id=int(TARGET_CHAT_ID), user_id=uid, can_manage_chat=True, can_invite_users=True)
                except: pass

                await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=uid, custom_title=title)
                logger.info(f"Успешно: {uid} -> {title}")
                await asyncio.sleep(0.8)
            except Exception as e:
                logger.warning(f"Ошибка для {tg_id}: {e}")

# ========================= ЛОГИКА ДНЕЙ РОЖДЕНИЙ =========================
async def check_birthdays(monthly_list=False):
    logger.info(f"--- СТАРТ ПРОВЕРКИ ДР ---")
    if not SHEET_BIRTHDAYS_URL: return

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    congrats_list = []
    month_list = []
    today_mentions = []

    try:
        res = requests.get(SHEET_BIRTHDAYS_URL, timeout=30)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text)).fillna("")
    except Exception as e:
        logger.error(f"Ошибка таблицы ДР: {e}"); return

    for _, row in df.iterrows():
        try:
            name = str(row['name']).strip()
            bd_val = str(row['birthday']).strip()
            if not bd_val or bd_val.lower() == "nan": continue
            parts = bd_val.replace('/', '.').replace('-', '.').split('.')
            if len(parts) < 2: continue
            
            d_t, m_t = int(float(parts[0])), int(float(parts[1]))
            
            if monthly_list:
                if m_t == now.month:
                    month_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
            elif d_t == now.day and m_t == now.month:
                username = str(row.get('username', '')).strip()
                clean_un = username.replace('@','')
                
                if clean_un and clean_un.lower() not in ["nan", "none", ""]:
                    mention = f"@{clean_un}"
                    today_mentions.append(f"@{clean_un}")
                else:
                    mention = html.escape(name)
                    today_mentions.append(name)

                age_text = ""
                if len(parts) == 3:
                    try:
                        year_t = int(float(parts[2]))
                        if 1900 < year_t < now.year: age_text = f" ({now.year - year_t} лет)"
                    except: pass
                congrats_list.append(f"<b>{mention}</b>{age_text}")
        except: continue

    bot = Bot(token=TOKEN)
    async with bot:
        if monthly_list and month_list:
            months = ["Январе", "Феврале", "Марте", "Апреле", "Мае", "Июне", "Июле", "Августе", "Сентябре", "Октябре", "Ноябре", "Декабре"]
            msg = f"🎂 <b>Именинники в {months[now.month-1]}:</b>\n\n" + "\n".join(sorted(month_list))
            await bot.send_message(chat_id=int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif not monthly_list and congrats_list:
            all_nicks = ", ".join(today_mentions)
            congrats_text = f"{all_nicks}, с днем рождения! 🎉 Желаю легких ног и крутых рекордов! 🏃‍♂️"
            
            congrats_names_block = "\n".join(congrats_list)
            
            msg = (
                f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n"
                f"{congrats_names_block}\n\n"
                f"Поздравляем! 🎉\n\n"
                f"📝 <b>Инструкция для поздравления:</b>\n"
                f"1. Нажмите на кнопку <b>«🥳 Поздравить 🥳»</b>\n"
                f"2. Удерживайте поле ввода и выберите <b>«Вставить»</b>"
            )

            btn_copy = InlineKeyboardButton(
                text="🥳 Поздравить 🥳", 
                copy_text=CopyTextButton(text=congrats_text)
            )

            await bot.send_message(
                chat_id=int(TARGET_CHAT_ID), 
                text=msg, 
                parse_mode=ParseMode.HTML, 
                reply_markup=InlineKeyboardMarkup([[btn_copy]]),
                message_thread_id=THREAD_ID
            )

# ========================= ПОГОДА =========================
async def send_weather():
    city = "Kstovo" 
    try:
        # Увеличил таймаут и добавил проверку на ошибки
        r = requests.get(f"https://wttr.in/{city}?format=%c+%t,+%C,+ощущается+как+%f&lang=ru", timeout=15)
        r.raise_for_status()
        weather_text = r.text.strip()
        
        bot = Bot(token=TOKEN)
        msg = f"<b>Прогноз погоды на сегодняшний старт в Кстово:</b>\n\n🌡 {weather_text}\n\nОдевайтесь по погоде и берите с собой горячий чай! ☕️🏃‍♂️"
        async with bot:
            await bot.send_message(
                chat_id=int(TARGET_CHAT_ID), 
                text=msg, 
                parse_mode=ParseMode.HTML, 
                message_thread_id=THREAD_ID
            )
        logger.info("Погода отправлена успешно.")
    except Exception as e:
        logger.error(f"Ошибка погоды: {e}")

# ========================= MAIN =========================
async def main():
    if len(sys.argv) < 2: return
    mode = sys.argv[1]
    if mode == "--titles": await update_titles()
    elif mode == "--birthdays": await check_birthdays(monthly_list=False)
    elif mode == "--birthdays-month": await check_birthdays(monthly_list=True)
    elif mode == "--weather": await send_weather()

if __name__ == "__main__":
    asyncio.run(main())
