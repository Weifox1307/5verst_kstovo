import os
import logging
import json
import asyncio
import requests
import re
import html
import pytz
import sys
import subprocess
from io import StringIO
from datetime import datetime, timedelta
import pandas as pd
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

# ========================= КОНФИГ =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID", "-1002607891507")
ORGS_CHAT_ID = os.getenv("ORGS_CHAT_ID")
TIMEZONE = "Europe/Moscow"

NRMS_USERNAME = os.getenv("NRMS_USERNAME")
NRMS_PASSWORD = os.getenv("NRMS_PASSWORD")
SHEET_BASE_URL = os.getenv("SHEET_BASE_URL")
SHEET_FORM_URL = os.getenv("SHEET_FORM_URL")
CACHE_FILE = "5verst_cache.json"
LOG_FILE = "last_report.txt"
VK_MEMBERS_FILE = "vk_members.json"

SHEET_BIRTHDAYS_URL = os.getenv("SHEET_BIRTHDAYS_URL")
THREAD_ID_ENV = os.getenv("THREAD_ID")
THREAD_ID = int(THREAD_ID_ENV) if THREAD_ID_ENV and THREAD_ID_ENV.strip() else None

# Настройки для Кстово Юбилейный
EVENT_ID = 10079
VK_GROUP_ID = 231094435 
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

# ========================= ЛОГИКА ВК =========================
async def update_vk_status():
    if not VK_TOKEN:
        logger.error("VK_TOKEN не настроен")
        return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    days_ahead = (5 - now.weekday()) % 7
    if days_ahead == 0 and now.hour > 11:
        days_ahead = 7
    next_sat = now + timedelta(days=days_ahead)
    date_str = next_sat.strftime("%d.%m.%Y")
    status_text = f"Следующий старт: {date_str} в 09:00! Ждём вас в парке Юбилейный 🌳"
    start_ts = int(next_sat.replace(hour=8, minute=40, second=0, microsecond=0).timestamp())
    end_ts = int(next_sat.replace(hour=10, minute=0, second=0, microsecond=0).timestamp())
    try:
        requests.get("https://api.vk.com/method/status.set", 
                     params={"group_id": VK_GROUP_ID, "text": status_text, "access_token": VK_TOKEN, "v": "5.131"})
        edit_params = {"group_id": VK_GROUP_ID, "event_start_date": start_ts, "event_finish_date": end_ts, "access_token": VK_TOKEN, "v": "5.131"}
        requests.get("https://api.vk.com/method/groups.edit", params=edit_params)
        logger.info(f"Статус ВК обновлен на {date_str}")
    except Exception as e:
        logger.error(f"Ошибка ВК: {e}")

# ========================= ЛОГИКА ТИТУЛОВ =========================
async def update_titles():
    logger.info("--- ОБНОВЛЕНИЕ ТИТУЛОВ ---")
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
            tg_id = extract_id(row.iloc)
            if tg_id: valid_chat_members.add(str(tg_id))
    except Exception as e: logger.error(f"Ошибка Sheet1: {e}")

    try:
        res_form = requests.get(SHEET_FORM_URL, timeout=20)
        df_form = pd.read_csv(StringIO(res_form.text))
        for _, row in df_form.iterrows():
            f_tg_id = extract_id(row.iloc)
            f_v5_id = extract_id(row.iloc)
            if f_tg_id and f_v5_id and f_tg_id in valid_chat_members:
                if str(TARGET_CHAT_ID) not in cache: cache[str(TARGET_CHAT_ID)] = {}
                cache[str(TARGET_CHAT_ID)][str(f_tg_id)] = int(f_v5_id)
    except Exception as e: logger.error(f"Ошибка формы: {e}")

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
                try:
                    await bot.promote_chat_member(chat_id=int(TARGET_CHAT_ID), user_id=int(tg_id), can_manage_chat=True)
                except: pass
                await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=int(tg_id), custom_title=title)
                await asyncio.sleep(0.8)
            except Exception as e: logger.warning(f"Ошибка титула {tg_id}: {e}")

# ========================= ЛОГИКА РЕЗУЛЬТАТОВ =========================
def get_results_data(date_str):
    url_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    url = f"https://5verst.ru/kstovoyubileyniy/results/{url_date}/"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            rows = soup.select("table.sortable tbody tr")
            count = sum(1 for row in rows if row.find_all("td") and row.find_all("td").get_text(strip=True).isdigit())
            h1 = soup.find('h1').get_text() if soup.find('h1') else ""
            match = re.search(r'(?:№|#|старта)\s*(\d+)', h1, re.IGNORECASE)
            return count, url, match.group(1) if match else None
    except: pass
    return 0, url, None

def get_vk_photo(display_date, run_num):
    if not VK_TOKEN: return f"https://vk.com/albums-{VK_GROUP_ID}", None
    try:
        day, month = display_date.split('.')[:2]
        date_pattern = f"{day}{month}"
        resp = requests.get("https://api.vk.com/method/photos.getAlbums", params={"owner_id": -VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131"}).json()
        albums = resp.get("response", {}).get("items", [])
        target = next((a for a in albums if date_pattern in re.sub(r'\D', '', a.get('title', ''))), None)
        if not target and run_num: target = next((a for a in albums if f"#{run_num}" in a.get('title', '')), None)
        if not target and albums: target = albums
        if target:
            album_url = f"https://vk.com/album-{VK_GROUP_ID}_{target['id']}"
            photos = requests.get("https://api.vk.com/method/photos.get", params={"owner_id": -VK_GROUP_ID, "album_id": target['id'], "access_token": VK_TOKEN, "v": "5.131", "count": 1}).json()
            items = photos.get("response", {}).get("items", [])
            if items: return album_url, sorted(items.get("sizes", []), key=lambda x: x['width'])[-1]['url']
    except: pass
    return f"https://vk.com/albums-{VK_GROUP_ID}", None

async def send_results():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    last_sat = now - timedelta(days=(now.weekday() - 5) % 7)
    date_str, disp_date = last_sat.strftime("%Y-%m-%d"), last_sat.strftime("%d.%m.%Y")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f.read().strip() == disp_date: return
    count, web_url, run_num = get_results_data(date_str)
    if count == 0: return
    
    v_text = ""
    headers = login_5verst()
    if headers:
        try:
            rv = requests.post("https://nrms.5verst.ru/api/v1/event/volunteer/list", json={"event_id": EVENT_ID, "event_date": disp_date}, headers=headers).json()
            v_list = rv.get("result", {}).get("volunteer_list", [])
            if v_list:
                vols = {}
                for v in v_list: vols[v['full_name']] = vols.get(v['full_name'], []) + [v['role_name']]
                v_text = f"\n🧡 <b>Герои ({len(vols)}):</b>\n" + "\n".join([f"• <b>{k}</b> — <i>{', '.join(v)}</i>" for k,v in vols.items()])
        except: pass

    alb_url, img = get_vk_photo(disp_date, run_num)
    msg = (f"🌳 <b>5 вёрст Юбилейный | Кстово</b>\n🗓 <b>Старт {disp_date}</b>\n━━━━━━━━━━━━━━\n🏁 Финишировало: <b>{count}</b>\n{v_text}\n\n📊 <a href='{web_url}'>Протокол</a>\n📸 <a href='{alb_url}'>Фото</a>")
    bot = Bot(token=TOKEN)
    async with bot:
        if img: await bot.send_photo(int(TARGET_CHAT_ID), photo=img, caption=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        else: await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        with open(LOG_FILE, "w") as f: f.write(disp_date)
        git_push()
        await update_vk_status()

def git_push():
    try:
        subprocess.run(["git", "config", "user.name", "Action Bot"], check=False)
        subprocess.run(["git", "config", "user.email", "bot@github.com"], check=False)
        subprocess.run(["git", "add", LOG_FILE, VK_MEMBERS_FILE], check=False)
        subprocess.run(["git", "commit", "-m", "Sync"], check=False)
        subprocess.run(["git", "push"], check=False)
    except: pass

# ========================= ДНИ РОЖДЕНИЯ =========================
async def check_birthdays(mode="day"):
    print(f"[DEBUG] Режим: {mode}")
    if not SHEET_BIRTHDAYS_URL: return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    try:
        res = requests.get(SHEET_BIRTHDAYS_URL)
        df = pd.read_csv(StringIO(res.text)).fillna("")
    except Exception as e: print(f"Ошибка таблицы: {e}"); return

    congrats, report_list = [], []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
    sunday = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59)

    # Маппинг колонок по индексу (0: name, 1: username, 2: birthday)
    for _, row in df.iterrows():
        try:
            name = str(row.iloc).strip()
            uname = str(row.iloc).strip().replace('@', '')
            bd_str = str(row.iloc).strip().replace('/', '.').replace('-', '.')
            if not bd_str or bd_str.lower() == 'nan': continue
            
            parts = bd_str.split('.')
            d_t, m_t = int(float(parts)), int(float(parts))

            if mode == "month" and m_t == now.month:
                report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
            elif mode == "day" and d_t == now.day and m_t == now.month:
                mention = f"@{uname}" if uname and uname.lower() != "nan" else html.escape(name)
                congrats.append(f"<b>{mention}</b>")
            elif mode == "week":
                bd_date = datetime(now.year, m_t, d_t).replace(tzinfo=tz)
                if monday <= bd_date <= sunday:
                    report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
        except: continue

    bot = Bot(token=TOKEN)
    async with bot:
        text = ""
        if mode == "month" and report_list: text = f"🎂 <b>Именинники месяца:</b>\n\n" + "\n".join(sorted(report_list))
        elif mode == "week" and report_list: text = f"📅 <b>Дни рождения на неделе:</b>\n\n" + "\n".join(sorted(report_list))
        elif mode == "day" and congrats: text = f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n" + "\n".join(congrats)
        
        if text: await bot.send_message(int(TARGET_CHAT_ID), text=text, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)

async def check_new_vk_members():
    if not VK_TOKEN: return
    try:
        r = requests.get("https://api.vk.com/method/groups.getMembers", params={"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "fields": "first_name,last_name"}).json()
        curr = r.get("response", {}).get("items", [])
        old = set(json.load(open(VK_MEMBERS_FILE)) if os.path.exists(VK_MEMBERS_FILE) else [])
        new = [f"<a href='https://vk.com/id{m['id']}'>{m['first_name']} {m['last_name']}</a>" for m in curr if m['id'] not in old and old]
        if new:
            async with Bot(token=TOKEN) as bot:
                await bot.send_message(int(TARGET_CHAT_ID), text=f"⚡️ <b>Новый подписчик ВК!</b>\n\n{', '.join(new)} 🎉", parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        json.dump([m['id'] for m in curr], open(VK_MEMBERS_FILE, "w"))
        if new: git_push()
    except: pass

async def main():
    if len(sys.argv) < 2: return
    arg = sys.argv
    if arg == "--titles": await update_titles()
    elif arg == "--results": await send_results()
    elif arg == "--vk-check": await check_new_vk_members()
    elif arg == "--vk-update": await update_vk_status()
    elif "--birthdays" in arg:
        mode = "day"
        if "week" in arg: mode = "week"
        elif "month" in arg: mode = "month"
        elif "auto" in arg:
            now = datetime.now(pytz.timezone(TIMEZONE))
            await check_birthdays("day")
            if now.day == 1: await check_birthdays("month")
            if now.weekday() == 0: await check_birthdays("week")
            return
        await check_birthdays(mode)

if __name__ == "__main__":
    asyncio.run(main())
