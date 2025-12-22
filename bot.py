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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
# Ссылка на CSV твоей таблицы с ответами формы
SHEET_CSV_URL = os.getenv("https://docs.google.com/spreadsheets/d/e/2PACX-1vRGoVLS0q1-9QsOOxuiTzVtY5MgSJjN_hQpmV_1BTSPWk9Od280xyog2i14EcYeQYlG-qm8T5_mX6ub/pub?gid=1335132952&single=true&output=csv") 
CACHE_FILE = "5verst_cache.json"

API_LOGIN_URL = "https://nrms.5verst.ru/api/v1/auth/login"
API_GET_STATS = "https://nrms.5verst.ru/api/v1/website/athlete/statById"
api_headers = {}

# ========================= ЛОГИКА ИЗВЛЕЧЕНИЯ ID =========================
def extract_tg_id(input_str):
    """Достает ID или Username из ссылок любого типа"""
    input_str = str(input_str).strip()
    # Если это ссылка web.telegram.org/k/#12345678
    if "#" in input_str:
        return input_str.split("#")[-1]
    # Если это ссылка t.me/12345678 или t.me/username
    if "t.me/" in input_str:
        return input_str.split("/")[-1]
    # Если это просто ID или username
    return input_str.replace("@", "")

# ========================= API 5ВЁРСТ =========================
def login_5verst():
    global api_headers
    try:
        r = requests.post(API_LOGIN_URL, json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        token = r.json().get("result", {}).get("token")
        if token:
            api_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            return True
    except Exception as e:
        logging.error(f"Ошибка входа 5в: {e}")
    return False

def get_stats(aid):
    try:
        # Убираем букву А, если она есть, для запроса к API
        clean_id = int(re.sub(r"\D", "", str(aid)))
        r = requests.post(API_GET_STATS, json={"id": clean_id}, headers=api_headers, timeout=15)
        return r.json().get("result")
    except: return None

def make_title(stats):
    if not stats: return "Новичок"
    m = stats.get("personal_best", {}).get("club_membership", {})
    run = {"run500": "500", "run250": "250", "run100": "100", "run50": "50", "run25": "25", "run10": "10"}.get(m.get("run"), "")
    vol = {"vol500": "500", "vol250": "250", "vol100": "100", "vol50": "50", "vol25": "25", "vol10": "10"}.get(m.get("volunteer"), "")
    badges = [b for b in [run, vol] if b]
    return f"Клуб {'|'.join(badges)}" if badges else "Новичок"

# ========================= ОСНОВНОЙ ПРОЦЕСС =========================
async def main():
    logging.info("Запуск обновления...")
    
    # 1. Загружаем старый кэш
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
    else:
        cache = {}

    # 2. Качаем данные из таблицы
    try:
        res = requests.get(SHEET_CSV_URL)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text))
        
        # Предположим: 1-я колонка время, 2-я TG, 3-я ID 5в
        # Лучше обращаться по индексам, если названия колонок длинные
        for _, row in df.iterrows():
            raw_tg = row.iloc[1] 
            raw_5v = row.iloc[2]
            
            tg_val = extract_tg_id(raw_tg)
            v5_val = int(re.sub(r"\D", "", str(raw_5v)))
            
            # Добавляем в основной чат (ID твоего чата из логов)
            chat_id = "-1002607891507"
            if chat_id not in cache: cache[chat_id] = {}
            cache[chat_id][str(tg_val)] = v5_val
    except Exception as e:
        logging.error(f"Ошибка чтения таблицы: {e}")

    # 3. Сохраняем обновленный кэш
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    # 4. Обновляем титулы в ТГ
    if login_5verst():
        bot = Bot(token=TOKEN)
        for chat_id, users in cache.items():
            for tg_id, v5_id in users.items():
                stats = get_stats(v5_id)
                title = make_title(stats)
                try:
                    # Если tg_id это цифры - используем как int, если буквы - как username
                    user_key = int(tg_id) if tg_id.isdigit() else f"@{tg_id}"
                    await bot.set_chat_administrator_custom_title(
                        chat_id=int(chat_id), 
                        user_id=user_key, 
                        custom_title=title
                    )
                    logging.info(f"OK: {user_key} -> {title}")
                except Exception as e:
                    logging.warning(f"Skip {tg_id}: {e}")
                await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
