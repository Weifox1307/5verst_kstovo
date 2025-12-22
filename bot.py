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

# Ссылки на CSV из секретов
SHEET_BASE_URL = os.getenv("https://docs.google.com/spreadsheets/d/e/2PACX-1vRGoVLS0q1-9QsOOxuiTzVtY5MgSJjN_hQpmV_1BTSPWk9Od280xyog2i14EcYeQYlG-qm8T5_mX6ub/pub?gid=1335132952&single=true&output=csv")  # Твоя база на 366 чел
SHEET_FORM_URL = os.getenv("https://docs.google.com/spreadsheets/d/e/2PACX-1vRGoVLS0q1-9QsOOxuiTzVtY5MgSJjN_hQpmV_1BTSPWk9Od280xyog2i14EcYeQYlG-qm8T5_mX6ub/pub?gid=1201534170&single=true&output=csv")  # Ответы из формы
CACHE_FILE = "5verst_cache.json"

API_LOGIN_URL = "https://nrms.5verst.ru/api/v1/auth/login"
API_GET_STATS = "https://nrms.5verst.ru/api/v1/website/athlete/statById"
TARGET_CHAT_ID = "-1002607891507"
api_headers = {}

# ========================= ЛОГИКА =========================
def extract_tg_id(input_str):
    s = str(input_str).strip()
    if not s or s.lower() == 'nan': return None
    if "#" in s: return s.split("#")[-1]
    if "t.me/" in s: return s.split("/")[-1].replace("@", "")
    return s.replace("@", "")

def login_5verst():
    global api_headers
    try:
        r = requests.post("https://nrms.5verst.ru/api/v1/auth/login", 
                          json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        token = r.json().get("result", {}).get("token")
        if token:
            api_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            return True
    except Exception as e:
        logging.error(f"Ошибка входа 5в: {e}")
    return False

def get_stats(aid):
    try:
        clean_id = int(re.sub(r"\D", "", str(aid)))
        r = requests.post("https://nrms.5verst.ru/api/v1/website/athlete/statById", 
                          json={"id": clean_id}, headers=api_headers, timeout=15)
        return r.json().get("result")
    except: return None

def make_title(stats):
    if not stats: return "Новичок"
    m = stats.get("personal_best", {}).get("club_membership", {})
    run = {"run500": "500", "run250": "250", "run100": "100", "run50": "50", "run25": "25", "run10": "10"}.get(m.get("run"), "")
    vol = {"vol500": "500", "vol250": "250", "vol100": "100", "vol50": "50", "vol25": "25", "vol10": "10"}.get(m.get("volunteer"), "")
    badges = [b for b in [run, vol] if b]
    return f"Клуб {'|'.join(badges)}" if badges else "Новичок"

async def main():
    logging.info("--- Начинаю синхронизацию ---")
    
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {TARGET_CHAT_ID: {}}

    def sync_sheet(url, name, tg_idx, v5_idx):
        if not url: 
            logging.warning(f"Ссылка для {name} не найдена в Secrets")
            return
        try:
            res = requests.get(url)
            res.encoding = 'utf-8'
            df = pd.read_csv(StringIO(res.text))
            
            logging.info(f"Таблица {name} скачана. Строк: {len(df)}")
            # Печатаем первые 2 строки для проверки структуры в логах
            logging.info(f"Пример данных {name}: \n{df.head(2).to_string()}")

            for i, row in df.iterrows():
                try:
                    tg = extract_tg_id(row.iloc[tg_idx])
                    v5_val = row.iloc[v5_idx]
                    if not tg or pd.isna(v5_val): continue
                    v5_id = int(re.sub(r"\D", "", str(v5_val)))
                    cache[TARGET_CHAT_ID][str(tg)] = v5_id
                except Exception as e:
                    continue
        except Exception as e:
            logging.error(f"Ошибка листа {name}: {e}")

    # СИНХРОНИЗАЦИЯ
    sync_sheet(SHEET_BASE_URL, "БАЗА_366", 0, 2) # Sheet1: TG(0), ID(2)
    sync_sheet(SHEET_FORM_URL, "ФОРМА_НОВЫЕ", 1, 2) # Форма: Время(0), TG(1), ID(2)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    # ОБНОВЛЕНИЕ ТИТУЛОВ
    if login_5verst():
        bot = Bot(token=TOKEN)
        users = cache.get(TARGET_CHAT_ID, {})
        logging.info(f"Итого пользователей для обработки: {len(users)}")
        
        for tg_id, v5_id in users.items():
            stats = get_stats(v5_id)
            title = make_title(stats)
            try:
                u_key = int(tg_id) if tg_id.isdigit() else f"@{tg_id}"
                await bot.set_chat_administrator_custom_title(
                    chat_id=int(TARGET_CHAT_ID), user_id=u_key, custom_title=title
                )
                logging.info(f"OK: {u_key} -> {title}")
            except Exception as e:
                logging.warning(f"Skip {tg_id}: {e}")
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
