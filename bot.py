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
from telegram import Bot
from telegram.constants import ParseMode

# ========================= КОНФИГ =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Общие данные
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = "-1002607891507"
TIMEZONE = "Europe/Moscow"

# Для ТИТУЛОВ
NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
SHEET_BASE_URL = os.getenv("SHEET_BASE_URL")
SHEET_FORM_URL = os.getenv("SHEET_FORM_URL")
CACHE_FILE = "5verst_cache.json"

# Для ДНЕЙ РОЖДЕНИЙ
# Создай этот секрет в GitHub Actions или замени ссылкой напрямую
SHEET_BIRTHDAYS_URL = os.getenv("SHEET_BIRTHDAYS_URL") 
THREAD_ID = os.getenv("THREAD_ID") # Если нужно слать в ветку

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
        token = r.json().get("result", {}).get("token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if token else None
    except: return None

# ========================= ЛОГИКА ТИТУЛОВ =========================
async def update_titles():
    logger.info("--- СТАРТ ОБНОВЛЕНИЯ ТИТУЛОВ ---")
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {TARGET_CHAT_ID: {}}

    # 1. Загрузка Базы и Формы (как в твоем исходном коде)
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
                cache[TARGET_CHAT_ID][str(f_tg_id)] = int(f_v5_id)
    except Exception as e:
        logger.error(f"Ошибка формы: {e}")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    headers = login_5verst()
    if not headers: return

    bot = Bot(token=TOKEN)
    for tg_id, v5_id in cache[TARGET_CHAT_ID].items():
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
async def check_birthdays():
    logger.info("--- СТАРТ ПРОВЕРКИ ДНЕЙ РОЖДЕНИЯ ---")
    if not SHEET_BIRTHDAYS_URL:
        logger.error("URL таблицы ДР не задан!")
        return

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    congrats_list = []

    try:
        res = requests.get(SHEET_BIRTHDAYS_URL)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text)).fillna("")
    except Exception as e:
        logger.error(f"Ошибка чтения таблицы ДР: {e}")
        return

    for _, row in df.iterrows():
        try:
            name = str(row['name']).strip()
            bd_val = str(row['birthday']).strip()
            if not bd_val or bd_val.lower() == "nan": continue

            clean_bd = bd_val.replace('/', '.').replace('-', '.')
            parts = clean_bd.split('.')
            if len(parts) < 2: continue
            
            d_t, m_t = int(float(parts[0])), int(float(parts[1]))
            
            if d_t == now.day and m_t == now.month:
                username = str(row.get('username', '')).strip()
                mention = f"@{username.replace('@','')}" if username and username.lower() not in ["nan", "none", ""] else html.escape(name)
                
                age_text = ""
                if len(parts) == 3:
                    try:
                        year_t = int(float(parts[2]))
                        if 1900 < year_t < now.year: age_text = f" ({now.year - year_t} лет)"
                    except: pass
                
                congrats_list.append(f"<b>{mention}</b>{age_text}")
        except: continue

    if congrats_list:
        bot = Bot(token=TOKEN)
        msg = f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n" + "\n".join(congrats_list) + "\n\nПоздравляем! 🎉🏃‍♂️"
        async with bot:
            await bot.send_message(
                chat_id=int(TARGET_CHAT_ID),
                text=msg,
                parse_mode=ParseMode.HTML,
                message_thread_id=int(THREAD_ID) if THREAD_ID else None
            )
        logger.info("Поздравления отправлены!")
    else:
        logger.info("Сегодня нет именинников.")

# ========================= ТОЧКА ВХОДА =========================
async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    if mode == "--titles":
        await update_titles()
    elif mode == "--birthdays":
        await check_birthdays()
    else:
        logger.error("Используйте флаг --titles или --birthdays")

if __name__ == "__main__":
    asyncio.run(main())
