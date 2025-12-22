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

# Берем ссылки из переменных окружения
SHEET_BASE_URL = os.getenv("SHEET_BASE_URL")
SHEET_FORM_URL = os.getenv("SHEET_FORM_URL")
CACHE_FILE = "5verst_cache.json"
TARGET_CHAT_ID = "-1002607891507"

# ========================= ЛОГИКА =========================
def extract_tg_id(input_str):
    s = str(input_str).strip()
    if not s or s.lower() == 'nan': return None
    # Извлекаем ID из ссылок или убираем @
    if "#" in s: return s.split("#")[-1]
    if "t.me/" in s: return s.split("/")[-1].replace("@", "")
    return s.replace("@", "")

def login_5verst():
    try:
        r = requests.post("https://nrms.5verst.ru/api/v1/auth/login", 
                          json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        token = r.json().get("result", {}).get("token")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if token else None
    except Exception as e:
        logging.error(f"Ошибка логина 5в: {e}")
        return None

async def main():
    logging.info("--- СТАРТ СИНХРОНИЗАЦИИ ---")
    
    # Загружаем текущий кэш
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {TARGET_CHAT_ID: {}}

    def process_sheet(url, name, tg_col, v5_col):
        if not url:
            logging.error(f"ПРОБЛЕМА: Переменная {name} ПУСТАЯ. Проверь секреты в GitHub!")
            return
        
        try:
            logging.info(f"Запрос данных для {name}...")
            res = requests.get(url, timeout=20)
            res.encoding = 'utf-8'
            df = pd.read_csv(StringIO(res.text))
            
            logging.info(f"Успех! {name} содержит {len(df)} строк.")
            # Печатаем колонки, чтобы ты видел индексы
            logging.info(f"Колонки в {name}: {list(df.columns)}")
            
            for i, row in df.iterrows():
                try:
                    tg_raw = row.iloc[tg_col]
                    v5_raw = row.iloc[v5_col]
                    
                    tg_clean = extract_tg_id(tg_raw)
                    v5_clean = int(re.sub(r"\D", "", str(v5_raw)))
                    
                    if tg_clean:
                        cache[TARGET_CHAT_ID][str(tg_clean)] = v5_clean
                except:
                    continue
        except Exception as e:
            logging.error(f"Ошибка при обработке {name}: {e}")

    # 1. Обработка Sheet1 (366 человек)
    # По твоей ссылке: Col 0 - ID, Col 1 - Name, Col 2 - Username, Col 3 - 5v ID
    # В Sheet1 обычно TG Username в колонке 2, ID 5в в колонке 3
    logging.info("Работаем с SHEET_BASE_URL (Sheet1)...")
    process_sheet(SHEET_BASE_URL, "SHEET_BASE", 2, 3) 

    # 2. Обработка Формы (Новые)
    # В форме обычно: 0 - Время, 1 - TG, 2 - ID 5в
    logging.info("Работаем с SHEET_FORM_URL (Форма)...")
    process_sheet(SHEET_FORM_URL, "SHEET_FORM", 1, 2)

    # Сохраняем кэш
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    logging.info(f"Кэш обновлен. Всего в базе: {len(cache[TARGET_CHAT_ID])} чел.")

    # 3. Обновление в ТГ
    headers = login_5verst()
    if not headers: return

    bot = Bot(token=TOKEN)
    for tg_id, v5_id in cache[TARGET_CHAT_ID].items():
        try:
            # Получаем статы
            r = requests.post("https://nrms.5verst.ru/api/v1/website/athlete/statById", 
                              json={"id": v5_id}, headers=headers, timeout=15)
            stats = r.json().get("result")
            
            # Логика титула
            m = stats.get("personal_best", {}).get("club_membership", {}) if stats else {}
            run = {"run500":"500","run250":"250","run100":"100","run50":"50","run25":"25","run10":"10"}.get(m.get("run"), "")
            vol = {"vol500":"500","vol250":"250","vol100":"100","vol50":"50","vol25":"25","vol10":"10"}.get(m.get("volunteer"), "")
            badges = [b for b in [run, vol] if b]
            title = f"Клуб {'|'.join(badges)}" if badges else "Новичок"

            u_key = int(tg_id) if tg_id.isdigit() else f"@{tg_id}"
            await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=u_key, custom_title=title)
            logging.info(f"Титул OK: {u_key} -> {title}")
        except Exception as e:
            logging.warning(f"Ошибка ТГ для {tg_id}: {e}")
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
