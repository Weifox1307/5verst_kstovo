import os
import logging
import json
import asyncio
import requests
import re
from typing import Optional, Dict
from telegram import Bot
from telegram.constants import ParseMode

# ========================= ЛОГИРОВАНИЕ =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========================= КОНФИГ ИЗ СЕКРЕТОВ =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
CACHE_FILE = "5verst_cache.json"

# API URLS
API_LOGIN_URL = "https://nrms.5verst.ru/api/v1/auth/login"
API_GET_STATS = "https://nrms.5verst.ru/api/v1/website/athlete/statById"

# Глобальные заголовки для API
api_headers = {}

# ========================= РАБОТА С КЭШЕМ =========================
def load_cache() -> Dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки кэша: {e}")
    return {}

# ========================= СИСТЕМА 5ВЁРСТ =========================
def login_5verst():
    global api_headers
    try:
        r = requests.post(API_LOGIN_URL, json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD}, timeout=15)
        r.raise_for_status()
        token = r.json().get("result", {}).get("token")
        if token:
            api_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            return True
    except Exception as e:
        logging.error(f"Ошибка входа в 5вёрст: {e}")
    return False

def get_stats(aid: int) -> Optional[dict]:
    try:
        r = requests.post(API_GET_STATS, json={"id": aid}, headers=api_headers, timeout=15)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        logging.error(f"Ошибка получения статистики ID {aid}: {e}")
        return None

def make_club_title(stats: dict) -> str:
    m = stats.get("personal_best", {}).get("club_membership", {})
    run = {"run500": "500", "run250": "250", "run100": "100", "run50": "50", "run25": "25", "run10": "10"}.get(m.get("run"), "")
    vol = {"vol500": "500", "vol250": "250", "vol100": "100", "vol50": "50", "vol25": "25", "vol10": "10"}.get(m.get("volunteer"), "")
    badges = [b for b in [run, vol] if b]
    return f"Клуб {'|'.join(badges)}" if badges else "Новичок"

# ========================= ОБНОВЛЕНИЕ ТИТУЛОВ =========================
async def update_all_titles():
    if not login_5verst():
        logging.error("Не удалось авторизоваться в системе 5вёрст. Выход.")
        return

    cache = load_cache()
    if not cache:
        logging.info("Кэш пуст. Некого обновлять.")
        return

    bot = Bot(token=TOKEN)
    
    # Перебор всех чатов и пользователей в кэше
    for chat_id_str, users in cache.items():
        chat_id = int(chat_id_str)
        for tg_id_str, aid in users.items():
            tg_id = int(tg_id_str)
            
            stats = get_stats(aid)
            if stats:
                new_title = make_club_title(stats)
                try:
                    # Пытаемся установить титул
                    await bot.set_chat_administrator_custom_title(
                        chat_id=chat_id, 
                        user_id=tg_id, 
                        custom_title=new_title
                    )
                    logging.info(f"Обновлен титул для {tg_id} в чате {chat_id}: {new_title}")
                except Exception as e:
                    logging.warning(f"Не удалось обновить титул для {tg_id}: {e}")
            
            # Небольшая пауза, чтобы Telegram не забанил за спам запросами
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(update_all_titles())
