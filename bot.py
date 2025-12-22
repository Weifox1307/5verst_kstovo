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

async def main():
    logging.info("--- СТАРТ СИНХРОНИЗАЦИИ ---")
    
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {TARGET_CHAT_ID: {}}

    # 1. Загрузка Базы (Sheet1)
    valid_chat_members = set()
    try:
        res_base = requests.get(SHEET_BASE_URL, timeout=20)
        if '<!DOCTYPE' not in res_base.text:
            df_base = pd.read_csv(StringIO(res_base.text))
            for _, row in df_base.iterrows():
                tg_id = extract_id(row.iloc[0])
                if tg_id: valid_chat_members.add(str(tg_id))
    except Exception as e:
        logging.error(f"Ошибка Sheet1: {e}")

    # 2. Загрузка Формы
    try:
        res_form = requests.get(SHEET_FORM_URL, timeout=20)
        if '<!DOCTYPE' not in res_form.text:
            df_form = pd.read_csv(StringIO(res_form.text))
            for _, row in df_form.iterrows():
                try:
                    form_tg_id = extract_id(row.iloc[1])
                    form_v5_id = extract_id(row.iloc[2])
                    if form_tg_id and form_v5_id and form_tg_id in valid_chat_members:
                        cache[TARGET_CHAT_ID][str(form_tg_id)] = int(form_v5_id)
                except: continue
    except Exception as e:
        logging.error(f"Ошибка формы: {e}")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    # 3. Работа с Telegram
    headers = login_5verst()
    if not headers: return

    bot = Bot(token=TOKEN)
    for tg_id, v5_id in cache[TARGET_CHAT_ID].items():
        try:
            # Получаем статы 5в
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

            # --- ШАГ: НАЗНАЧАЕМ АДМИНОМ (без прав) ---
            try:
                await bot.promote_chat_member(
                    chat_id=int(TARGET_CHAT_ID),
                    user_id=uid,
                    can_manage_chat=True, # Обязательно True для титула
                    can_invite_users=True # Минимальное безобидное право
                )
            except Exception as e:
                logging.info(f"Заметка для {uid}: Пользователь уже админ или нельзя повысить ({e})")

            # --- ШАГ: СТАВИМ ТИТУЛ ---
            await bot.set_chat_administrator_custom_title(
                chat_id=int(TARGET_CHAT_ID), 
                user_id=uid, 
                custom_title=title
            )
            logging.info(f"Успешно: {uid} -> {title}")

        except Exception as e:
            logging.warning(f"Ошибка для {tg_id}: {e}")
        await asyncio.sleep(0.8)

if __name__ == "__main__":
    asyncio.run(main())
