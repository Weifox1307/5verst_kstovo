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

def parse_flexible_date(date_str):
    """Извлекает день и месяц из любого формата (05.03, 5/3/1990 и т.д.)"""
    if not date_str or str(date_str).lower() == 'nan':
        return None, None
    clean = re.sub(r'[^0-9./-]', '.', str(date_str).strip())
    clean = clean.replace('/', '.').replace('-', '.')
    parts = [p for p in clean.split('.') if p.strip().isdigit()]
    if len(parts) >= 2:
        try:
            day, month = int(parts), int(parts)
            if 1 <= day <= 31 and 1 <= month <= 12:
                return day, month
        except: pass
    return None, None

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

# ========================= ЛОГИКА ВК (СТАТУС И ДАТА) =========================
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
        edit_params = {
            "group_id": VK_GROUP_ID,
            "event_start_date": start_ts,
            "event_finish_date": end_ts,
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
        res_edit = requests.get("https://api.vk.com/method/groups.edit", params=edit_params).json()
        if "error" in res_edit:
            logger.error(f"Ошибка обновления даты ВК: {res_edit['error']['error_msg']}")
        else:
            logger.info(f"Дата мероприятия ВК обновлена на {date_str}")
    except Exception as e:
        logger.error(f"Ошибка ВК API: {e}")

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
        res_base.encoding = 'utf-8'
        df_base = pd.read_csv(StringIO(res_base.text))
        for _, row in df_base.iterrows():
            tg_id = extract_id(row.iloc)
            if tg_id: valid_chat_members.add(str(tg_id))
    except Exception as e: logger.error(f"Ошибка Sheet1: {e}")
    try:
        res_form = requests.get(SHEET_FORM_URL, timeout=20)
        res_form.encoding = 'utf-8'
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
                uid = int(tg_id)
                try:
                    await bot.promote_chat_member(chat_id=int(TARGET_CHAT_ID), user_id=uid, can_manage_chat=True, can_invite_users=True)
                except: pass
                await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=uid, custom_title=title)
                await asyncio.sleep(0.8)
            except Exception as e: logger.warning(f"Ошибка для {tg_id}: {e}")

# ========================= ЛОГИКА РЕЗУЛЬТАТОВ =========================
def get_results_data(date_str):
    url_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    url = f"https://5verst.ru/kstovoyubileyniy/results/{url_date}/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = requests.get(url, timeout=20, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.select("table.sortable tbody tr")
            real_finishers = 0
            for row in rows:
                cells = row.find_all("td")
                if cells and cells.get_text(strip=True).isdigit():
                    real_finishers += 1
            if real_finishers > 0:
                h1_text = soup.find('h1').get_text() if soup.find('h1') else ""
                match = re.search(r'(?:№|#|старта)\s*(\d+)', h1_text, re.IGNORECASE)
                return real_finishers, url, match.group(1) if match else None
    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
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
        target = next((a for a in albums if date_pattern in re.sub(r'\D', '', a.get('title', ''))), None)
        if not target and run_num:
            target = next((a for a in albums if f"#{run_num}" in a.get('title', '')), None)
        if not target and albums: target = albums
        if target:
            album_url = f"https://vk.com/album-{VK_GROUP_ID}_{target['id']}"
            p_img = {"owner_id": -VK_GROUP_ID, "album_id": target['id'], "access_token": VK_TOKEN, "v": "5.131", "count": 1}
            photos = requests.get("https://api.vk.com/method/photos.get", params=p_img).json().get("response", {}).get("items", [])
            if photos:
                return album_url, sorted(photos.get("sizes", []), key=lambda x: x['width'])[-1]['url']
    except: pass
    return album_url, None

async def send_results():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    offset = (now.weekday() - 5) % 7
    last_sat = now - timedelta(days=offset)
    date_str, disp_date = last_sat.strftime("%Y-%m-%d"), last_sat.strftime("%d.%m.%Y")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f.read().strip() == disp_date: return
    count, web_url, run_num = get_results_data(date_str)
    if count == 0: return
    headers = login_5verst()
    vols_text, v_count_unique = "", 0
    if headers:
        try:
            r = requests.post("https://nrms.5verst.ru/api/v1/event/volunteer/list", 
                              json={"event_id": EVENT_ID, "event_date": disp_date}, headers=headers)
            v_list = r.json().get("result", {}).get("volunteer_list", [])
            if v_list:
                vols = {}
                for v in v_list:
                    n, rn = v.get("full_name"), v.get("role_name")
                    vols[n] = vols.get(n, []) + [rn]
                v_count_unique = len(vols)
                vols_text = f"\n🧡 <b>Команда героев ({v_count_unique}):</b>\n" + \
                            "\n".join([f"• <b>{name}</b> — <i>{', '.join(roles)}</i>" for name, roles in vols.items()])
        except: pass
    alb_url, img_url = get_vk_photo(disp_date, run_num)
    msg = (f"🌳 <b>5 вёрст парк Юбилейный | Кстово</b>\n🗓 <b>Старт от {disp_date}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n🏁 Финишировало: <b>{count}</b>\n{vols_text}\n\n"
            f"📊 <a href='{web_url}'>Протокол</a>\n📸 <a href='{alb_url}'>Фотографии</a>")
    bot = Bot(token=TOKEN)
    async with bot:
        try:
            if img_url: await bot.send_photo(int(TARGET_CHAT_ID), photo=img_url, caption=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            else: await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            with open(LOG_FILE, "w") as f: f.write(disp_date)
            git_push()
            await update_vk_status()
        except Exception as e: logger.error(f"Ошибка отправки результатов: {e}")

def git_push():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action Bot"])
        subprocess.run(["git", "config", "user.email", "actions@github.com"])
        subprocess.run(["git", "add", LOG_FILE, VK_MEMBERS_FILE])
        subprocess.run(["git", "commit", "-m", "Auto: Sync logs"])
        subprocess.run(["git", "push"])
    except: pass

# ========================= ДНИ РОЖДЕНИЯ =========================
async def check_birthdays(mode="day"):
    if not SHEET_BIRTHDAYS_URL: return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    try:
        res = requests.get(SHEET_BIRTHDAYS_URL, timeout=30)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text)).fillna("")
    except: return
    congrats, report_list = [], []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)
    for _, row in df.iterrows():
        try:
            name = str(row.iloc).strip()
            bd_val = str(row.iloc).strip()
            d_t, m_t = parse_flexible_date(bd_val)
            if d_t is None: continue
            if mode == "month" and m_t == now.month:
                report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
            elif mode == "day" and d_t == now.day and m_t == now.month:
                un = str(row.iloc).strip().replace('@','')
                mention = f"@{un}" if un and un.lower() not in ["nan",""] else html.escape(name)
                congrats.append(f"<b>{mention}</b>")
            elif mode == "week":
                bd_this_year = datetime(now.year, m_t, d_t).replace(tzinfo=tz)
                if monday <= bd_this_year <= sunday:
                    report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
        except: continue
    bot = Bot(token=TOKEN)
    async with bot:
        if mode == "month" and report_list:
            await bot.send_message(int(TARGET_CHAT_ID), text=f"🎂 <b>Именинники месяца:</b>\n\n"+"\n".join(sorted(report_list)), parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif mode == "week" and report_list:
            await bot.send_message(int(TARGET_CHAT_ID), text=f"📅 <b>Дни рождения на неделе:</b>\n\n"+"\n".join(sorted(report_list)), parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif mode == "day" and congrats:
            await bot.send_message(int(TARGET_CHAT_ID), text=f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n"+"\n".join(congrats), parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)

# ========================= ВК МОНИТОРИНГ =========================
async def check_new_vk_members():
    if not VK_TOKEN: return
    try:
        p = {"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131"}
        resp = requests.get("https://api.vk.com/method/groups.getMembers", params={**p, "fields": "first_name,last_name"}).json()
        current_members = resp.get("response", {}).get("items", [])
        old_ids = set(json.load(open(VK_MEMBERS_FILE)) if os.path.exists(VK_MEMBERS_FILE) else [])
        new_names = [f"<a href='https://vk.com/id{m['id']}'>{m['first_name']} {m['last_name']}</a>" for m in current_members if m['id'] not in old_ids and old_ids]
        if new_names:
            async with Bot(token=TOKEN) as bot:
                await bot.send_message(int(TARGET_CHAT_ID), text=f"⚡️ <b>Новый подписчик в ВК!</b>\n\n{', '.join(new_names)} 🎉", parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        json.dump([m['id'] for m in current_members], open(VK_MEMBERS_FILE, "w"))
        if new_names or not old_ids: git_push()
    except: pass

# ========================= ЕЖЕНЕДЕЛЬНЫЕ ИТОГИ =========================
async def send_weekly_stats():
    headers = login_5verst()
    if not headers or not VK_TOKEN: return
    bot = Bot(token=TOKEN)
    async with bot:
        try: tg_count = await bot.get_chat_member_count(int(TARGET_CHAT_ID))
        except: tg_count = "???"
        vk_r = requests.get("https://api.vk.com/method/groups.getMembers", params={"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "count": 0}).json()
        vk_count = vk_r.get("response", {}).get("count", "???")
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        offset = (now.weekday() - 5) % 7
        last_sat_dt = now - timedelta(days=offset)
        last_sat_str = last_sat_dt.strftime("%d.%m.%Y")
        count_finish, _, _ = get_results_data(last_sat_dt.strftime("%Y-%m-%d"))
        v_count_unique = 0
        try:
            v_resp = requests.post("https://nrms.5verst.ru/api/v1/event/volunteer/list", 
                                   json={"event_id": EVENT_ID, "event_date": last_sat_str}, headers=headers).json()
            v_list = v_resp.get("result", {}).get("volunteer_list", [])
            v_count_unique = len(set(v.get("full_name") for v in v_list))
        except: pass
        msg = (f"📈 <b>ИТОГИ НЕДЕЛИ | КСТОВО</b>\n\n"
               f"👥 <b>Сообщество:</b>\n"
               f"• Telegram: <b>{tg_count}</b>\n"
               f"• ВКонтакте: <b>{vk_count}</b>\n\n"
               f"🏃‍♂️ <b>Последний старт ({last_sat_str}):</b>\n"
               f"• Финишировало: <b>{count_finish}</b>\n"
               f"• Волонтеров: <b>{v_count_unique}</b>\n\n"
               f"🧡 Увидимся на 5 вёрст 🧡!")
        if ORGS_CHAT_ID:
            try: await bot.send_message(int(ORGS_CHAT_ID), text=msg, parse_mode=ParseMode.HTML)
            except Exception as e: logger.error(f"Ошибка в ORGS_CHAT_ID: {e}")

async def main():
    if len(sys.argv) < 2: return
    m = sys.argv
    if m == "--titles": await update_titles()
    elif m == "--birthdays": await check_birthdays("day")
    elif m == "--results": await send_results()
    elif m == "--vk-check": await check_new_vk_members()
    elif m == "--stats": await send_weekly_stats()
    elif m == "--vk-update": await update_vk_status()
    elif m == "--birthdays-auto":
        await check_birthdays("day")
        if datetime.now(pytz.timezone(TIMEZONE)).day == 1: await check_birthdays("month")
        if datetime.now(pytz.timezone(TIMEZONE)).weekday() == 0: await check_birthdays("week")

if __name__ == "__main__":
    asyncio.run(main())
