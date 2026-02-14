import os
import logging
import json
import asyncio
import requests
import re
import html
import pytz
import sys
import io
import subprocess
from io import StringIO
from datetime import datetime, timedelta
import pandas as pd
from bs4 import BeautifulSoup
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
LOG_FILE = "last_report.txt"

SHEET_BIRTHDAYS_URL = os.getenv("SHEET_BIRTHDAYS_URL") 
THREAD_ID_ENV = os.getenv("THREAD_ID")
THREAD_ID = int(THREAD_ID_ENV) if THREAD_ID_ENV and THREAD_ID_ENV.strip() else None

# Настройки для Кстово Юбилейный
EVENT_ID = 10079
VK_GROUP_ID = 231094435  # Группа Кстово Юбилейный
VK_TOKEN = os.getenv("VK_TOKEN")

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

# ========================= ЛОГИКА РЕЗУЛЬТАТОВ =========================
def get_results_data(date_str):
    url_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    # Используем путь для Юбилейного
    url = f"https://5verst.ru/kstovoyubileyniy/results/{url_date}/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, timeout=15, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            h1_text = soup.find('h1').get_text() if soup.find('h1') else ""
            match = re.search(r'(?:№|#|старта)\s*(\d+)', h1_text, re.IGNORECASE)
            run_num = match.group(1) if match else None
            table = soup.find('table', class_='sortable')
            if table and table.find('tbody'):
                count = len(table.find('tbody').find_all('tr'))
                if count > 0: return count, url, run_num
    except: pass
    return 0, url, None

def get_vk_photo(display_date, run_num):
    album_url = f"https://vk.com/albums-{VK_GROUP_ID}"
    if not VK_TOKEN: return album_url, None
    try:
        day, month, _ = display_date.split('.')
        date_pattern = f"{day}{month}"
        p = {"owner_id": -VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131"}
        resp = requests.get("https://api.vk.com/method/photos.getAlbums", params=p).json()
        albums = resp.get("response", {}).get("items", [])
        
        # Поиск альбома по дате или номеру
        target = next((a for a in albums if date_pattern in re.sub(r'\D', '', a.get('title', ''))), None)
        if not target and run_num:
            target = next((a for a in albums if f"#{run_num}" in a.get('title', '') or f"№{run_num}" in a.get('title', '')), None)
        if not target and albums: target = albums[0]
        
        if target:
            album_url = f"https://vk.com/album-{VK_GROUP_ID}_{target['id']}"
            p_img = {"owner_id": -VK_GROUP_ID, "album_id": target['id'], "access_token": VK_TOKEN, "v": "5.131", "count": 1}
            photos = requests.get("https://api.vk.com/method/photos.get", params=p_img).json().get("response", {}).get("items", [])
            if photos:
                return album_url, sorted(photos[0].get("sizes", []), key=lambda x: x['width'])[-1]['url']
    except: pass
    return album_url, None

async def send_results():
    logger.info("--- ПРОВЕРКА РЕЗУЛЬТАТОВ ---")
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    offset = (now.weekday() - 5) % 7
    last_sat = now - timedelta(days=offset)
    date_str, disp_date = last_sat.strftime("%Y-%m-%d"), last_sat.strftime("%d.%m.%Y")

    # Проверка на дубли через файл
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f.read().strip() == disp_date:
                logger.info("Отчет за эту дату уже был отправлен.")
                return

    count, web_url, run_num = get_results_data(date_str)
    if count == 0:
        logger.info(f"Результаты за {disp_date} еще не готовы.")
        return

    headers = login_5verst()
    vols_text = ""
    if headers:
        try:
            r = requests.post("https://nrms.5verst.ru/api/v1/event/volunteer/list", 
                              json={"event_id": EVENT_ID, "event_date": disp_date}, headers=headers)
            v_list = r.json().get("result", {}).get("volunteer_list", [])
            if v_list:
                vols = {}
                for v in v_list:
                    n, r = v.get("full_name"), v.get("role_name")
                    vols[n] = vols.get(n, []) + [r]
                vols_text = f"\n🧡 <b>Команда героев ({len(vols)}):</b> 💚\n" + \
                            "\n".join([f"• <b>{name}</b> — <i>{', '.join(roles)}</i>" for name, roles in vols.items()])
        except: pass

    alb_url, img_url = get_vk_photo(disp_date, run_num)
    msg = (f"🌳 <b>5 вёрст парк Юбилейный | Кстово</b>\n"
           f"🗓 <b>Старт от {disp_date}</b>\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"🏁 Финишировало участников: <b>{count}</b>\n"
           f"{vols_text}\n\n"
           f"📊 <a href='{web_url}'>Протокол</a>\n"
           f"📸 <a href='{alb_url}'>Фотографии</a>")

    bot = Bot(token=TOKEN)
    async with bot:
        try:
            if img_url:
                await bot.send_photo(int(TARGET_CHAT_ID), photo=img_url, caption=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            else:
                await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID, disable_web_page_preview=False)
            
            # Запоминаем отправку
            with open(LOG_FILE, "w") as f: f.write(disp_date)
            subprocess.run(["git", "config", "user.name", "GitHub Action Bot"])
            subprocess.run(["git", "config", "user.email", "actions@github.com"])
            subprocess.run(["git", "add", LOG_FILE])
            subprocess.run(["git", "commit", "-m", f"Auto: Report for {disp_date} sent"])
            subprocess.run(["git", "push"])
            logger.info("Отчет успешно отправлен и залогирован.")
        except Exception as e: logger.error(f"Ошибка отправки: {e}")

# ========================= ОСТАЛЬНАЯ ЛОГИКА (ДР И ПОГОДА) =========================
async def check_birthdays(monthly_list=False):
    if not SHEET_BIRTHDAYS_URL: return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    congrats_list, month_list, today_mentions = [], [], []

    try:
        res = requests.get(SHEET_BIRTHDAYS_URL, timeout=30)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text)).fillna("")
    except: return

    for _, row in df.iterrows():
        try:
            name, bd_val = str(row['name']).strip(), str(row['birthday']).strip()
            parts = bd_val.replace('/', '.').replace('-', '.').split('.')
            d_t, m_t = int(float(parts[0])), int(float(parts[1]))
            if monthly_list and m_t == now.month:
                month_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
            elif not monthly_list and d_t == now.day and m_t == now.month:
                un = str(row.get('username', '')).strip().replace('@','')
                mention = f"@{un}" if un and un.lower() not in ["nan",""] else html.escape(name)
                today_mentions.append(mention)
                age = f" ({now.year - int(float(parts[2]))} лет)" if len(parts)==3 else ""
                congrats_list.append(f"<b>{mention}</b>{age}")
        except: continue

    bot = Bot(token=TOKEN)
    async with bot:
        if monthly_list and month_list:
            months = ["Январе", "Феврале", "Марте", "Апреле", "Мае", "Июне", "Июле", "Августе", "Сентябре", "Октябре", "Ноябре", "Декабре"]
            msg = f"🎂 <b>Именинники в {months[now.month-1]}:</b>\n\n" + "\n".join(sorted(month_list))
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif not monthly_list and congrats_list:
            c_text = f"{', '.join(today_mentions)}, с днем рождения! 🎉"
            msg = f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n" + "\n".join(congrats_list)
            btn = InlineKeyboardMarkup([[InlineKeyboardButton(text="🥳 Поздравить 🥳", copy_text=CopyTextButton(text=c_text))]])
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, reply_markup=btn, message_thread_id=THREAD_ID)

async def send_weather():
    lat, lon = 56.15, 44.20 # Кстово
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&timezone=Europe%2FMoscow"
    try:
        r = requests.get(url).json().get("current", {})
        temp, code = r.get("temperature_2m"), r.get("weather_code", 0)
        msg = f"<b>Погода на старт:</b> {temp}°C. Хорошей пробежки! 🏃‍♂️"
        async with Bot(token=TOKEN) as bot:
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
    except: pass

async def main():
    if len(sys.argv) < 2: return
    mode = sys.argv[1]
    if mode == "--titles": await update_titles()
    elif mode == "--birthdays": await check_birthdays(False)
    elif mode == "--birthdays-month": await check_birthdays(True)
    elif mode == "--weather": await send_weather()
    elif mode == "--results": await send_results()
    elif mode == "--birthdays-auto":
        await check_birthdays(False)
        if datetime.now(pytz.timezone(TIMEZONE)).day == 1: await check_birthdays(True)

if __name__ == "__main__":
    asyncio.run(main())
