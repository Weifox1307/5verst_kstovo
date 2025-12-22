import os
import logging
import json
import asyncio
import requests
import re
from io import StringIO
import pandas as pd
from telegram import Bot

# ========================= КОНФИГ =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
SHEET_BASE_URL = os.getenv("SHEET_BASE_URL")
SHEET_FORM_URL = os.getenv("SHEET_FORM_URL")
CACHE_FILE = "5verst_cache.json"
TARGET_CHAT_ID = "-1002607891507"

# ========================= ЛОГИКА =========================
def extract_tg_id(input_str):
    s = str(input_str).strip()
    if not s or s.lower() == 'nan' or '<!DOCTYPE' in s or 'document.' in s:
        return None
    if "#" in s: return s.split("#")[-1]
    if "t.me/" in s: return s.split("/")[-1].replace("@", "")
    return s.replace("@", "")

def login_5verst():
    try:
        r = requests.post("https://nrms.5verst.ru/api/v1/auth/login", 
                          json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        token = r.json().get("result", {}).get("token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if token else None
    except: return None

async def main():
    logging.info("--- СИНХРОНИЗАЦИЯ ---")
    new_cache = {TARGET_CHAT_ID: {}}

    def process_sheet(url, name, tg_col, v5_col):
        if not url: return
        try:
            res = requests.get(url, timeout=20)
            if '<!DOCTYPE' in res.text:
                logging.error(f"ОШИБКА: Ссылка {name} ведет на страницу логина (HTML). Проверь публикацию CSV!")
                return
            
            df = pd.read_csv(StringIO(res.text))
            count = 0
            for _, row in df.iterrows():
                try:
                    tg = extract_tg_id(row.iloc[tg_col])
                    v5_val = row.iloc[v5_col]
                    if tg and not pd.isna(v5_val):
                        # Извлекаем только цифры (ID 5 верст)
                        v5_id = int(re.sub(r"\D", "", str(v5_val)))
                        new_cache[TARGET_CHAT_ID][str(tg)] = v5_id
                        count += 1
                except: continue
            logging.info(f"Успешно обработано из {name}: {count} чел.")
        except Exception as e:
            logging.error(f"Ошибка {name}: {e}")

    # БАЗА (365 чел): Username (2), ID (3)
    process_sheet(SHEET_BASE_URL, "БАЗА", 2, 3) 
    # ФОРМА: Telegram (1), ID (2)
    process_sheet(SHEET_FORM_URL, "ФОРМА", 1, 2)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_cache, f, indent=2, ensure_ascii=False)
    
    total = len(new_cache[TARGET_CHAT_ID])
    logging.info(f"Итого в кэше: {total} чел.")

    headers = login_5verst()
    if not headers or total == 0: return

    bot = Bot(token=TOKEN)
    for tg_id, v5_id in new_cache[TARGET_CHAT_ID].items():
        try:
            r = requests.post("https://nrms.5verst.ru/api/v1/website/athlete/statById", 
                              json={"id": v5_id}, headers=headers, timeout=15)
            stats = r.json().get("result")
            
            m = stats.get("personal_best", {}).get("club_membership", {}) if stats else {}
            run = {"run500":"500","run250":"250","run100":"100","run50":"50","run25":"25","run10":"10"}.get(m.get("run"), "")
            vol = {"vol500":"500","vol250":"250","vol100":"100","vol50":"50","vol25":"25","vol10":"10"}.get(m.get("volunteer"), "")
            badges = [b for b in [run, vol] if b]
            title = f"Клуб {'|'.join(badges)}" if badges else "Новичок"

            u_key = int(tg_id) if str(tg_id).isdigit() else f"@{tg_id}"
            await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=u_key, custom_title=title)
            logging.info(f"OK: {u_key} -> {title}")
        except Exception as e:
            logging.warning(f"Skip {tg_id}: {e}")
        await asyncio.sleep(0.6)

if __name__ == "__main__":
    asyncio.run(main())
