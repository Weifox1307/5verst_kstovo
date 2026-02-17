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
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
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

# ========================= ЛОГИКА ВК СТАТУСА =========================
async def update_vk_status():
    """Обновляет статус группы ВК на дату следующей субботы"""
    if not VK_TOKEN:
        logger.error("VK_TOKEN не настроен, пропуск обновления статуса")
        return

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    
    # Ищем следующую субботу
    # Если сегодня суббота и время > 11 утра, берем субботу через неделю
    days_ahead = (5 - now.weekday()) % 7
    if days_ahead == 0 and now.hour > 11:
        days_ahead = 7
    
    next_sat = now + timedelta(days=days_ahead)
    date_str = next_sat.strftime("%d.%m.%Y")
    
    status_text = f"Следующий старт: {date_str} в 09:00! Ждём вас в парке Юбилейный 🌳"
    
    try:
        url = "https://api.vk.com/method/status.set"
        params = {
            "group_id": VK_GROUP_ID,
            "text": status_text,
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
        res = requests.get(url, params=params).json()
        if "error" in res:
            logger.error(f"Ошибка ВК API при обновлении статуса: {res['error']['error_msg']}")
        else:
            logger.info(f"Статус ВК успешно обновлен: {status_text}")
    except Exception as e:
        logger.error(f"Не удалось обновить статус ВК: {e}")

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
    urls_to_check = [
        "https://5verst.ru/kstovoyubileyniy/results/latest/",
        f"https://5verst.ru/kstovoyubileyniy/results/{url_date}/"
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    for url in urls_to_check:
        try:
            response = requests.get(url, timeout=15, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', class_='sortable')
                if table and table.find('tbody'):
                    rows = table.find('tbody').find_all('tr')
                    count = len(rows)
                    if count > 0:
                        h1_text = soup.find('h1').get_text() if soup.find('h1') else ""
                        match = re.search(r'(?:№|#|старта)\s*(\d+)', h1_text, re.IGNORECASE)
                        run_num = match.group(1) if match else None
                        return count, url, run_num
        except: pass
    return 0, urls_to_check[0], None

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
    if now.weekday() == 5: last_sat = now
    else:
        offset = (now.weekday() - 5) % 7
        last_sat = now - timedelta(days=offset)
    date_str, disp_date = last_sat.strftime("%Y-%m-%d"), last_sat.strftime("%d.%m.%Y")

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f.read().strip() == disp_date: return

    count, web_url, run_num = get_results_data(date_str)
    if count == 0: return

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
                    n, rn = v.get("full_name"), v.get("role_name")
                    vols[n] = vols.get(n, []) + [rn]
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
                await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            with open(LOG_FILE, "w") as f: f.write(disp_date)
            git_push()
            
            # Сразу после успешных результатов обновляем ВК на следующую неделю
            await update_vk_status()
            
        except Exception as e: logger.error(f"Ошибка отправки: {e}")

def git_push():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action Bot"])
        subprocess.run(["git", "config", "user.email", "actions@github.com"])
        subprocess.run(["git", "add", LOG_FILE, VK_MEMBERS_FILE])
        subprocess.run(["git", "commit", "-m", "Auto: Update logs and members"])
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
    except Exception as e:
        logger.error(f"Ошибка загрузки таблицы ДР: {e}")
        return

    congrats, report_list = [], []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)

    for _, row in df.iterrows():
        try:
            name, bd_val = str(row['name']).strip(), str(row['birthday']).strip()
            bd_val = bd_val.replace('/', '.').replace('-', '.')
            parts = bd_val.split('.')
            d_t, m_t = int(float(parts[0])), int(float(parts[1]))
            
            if mode == "month" and m_t == now.month:
                report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
            elif mode == "day" and d_t == now.day and m_t == now.month:
                un = str(row.get('username', '')).strip().replace('@','')
                mention = f"@{un}" if un and un.lower() not in ["nan",""] else html.escape(name)
                age = f" ({now.year - int(float(parts[2]))} лет)" if len(parts)==3 else ""
                congrats.append(f"<b>{mention}</b>{age}")
            elif mode == "week":
                bd_this_year = datetime(now.year, m_t, d_t).replace(tzinfo=tz)
                if monday <= bd_this_year <= sunday:
                    report_list.append(f"• {d_t:02d}.{m_t:02d} — {html.escape(name)}")
        except: continue

    bot = Bot(token=TOKEN)
    async with bot:
        if mode == "month" and report_list:
            months = ["Январе", "Феврале", "Марте", "Апреле", "Мае", "Июне", "Июле", "Августе", "Сентябре", "Октябре", "Ноябре", "Декабре"]
            msg = f"🎂 <b>Именинники в {months[now.month-1]}:</b>\n\n" + "\n".join(sorted(report_list))
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif mode == "week":
            if report_list:
                msg = f"📅 <b>Дни рождения на этой неделе ({monday.strftime('%d.%m')} - {sunday.strftime('%d.%m')}):</b>\n\n" + "\n".join(sorted(report_list))
                await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
        elif mode == "day" and congrats:
            msg = f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n" + "\n".join(congrats)
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)

# ========================= ВК ЧЕК И СТАТИСТИКА =========================
async def check_new_vk_members():
    if not VK_TOKEN: return
    try:
        p = {"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "fields": "first_name,last_name"}
        resp = requests.get("https://api.vk.com/method/groups.getMembers", params=p).json()
        current_members = resp.get("response", {}).get("items", [])
        
        if os.path.exists(VK_MEMBERS_FILE):
            with open(VK_MEMBERS_FILE, "r") as f: old_ids = set(json.load(f))
        else: old_ids = set()

        new_names = []
        current_ids = []
        for m in current_members:
            mid = m.get("id")
            current_ids.append(mid)
            if mid not in old_ids and old_ids:
                new_names.append(f"<a href='https://vk.com/id{mid}'>{m.get('first_name')} {m.get('last_name')}</a>")

        if new_names:
            msg = f"⚡️ <b>Новый подписчик в ВК!</b>\n\nДобро пожаловать в семью: {', '.join(new_names)} 🎉"
            async with Bot(token=TOKEN) as bot:
                await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)

        with open(VK_MEMBERS_FILE, "w") as f: json.dump(current_ids, f)
        if len(new_names) > 0 or not old_ids: git_push()
    except Exception as e: logger.error(f"VK Members Error: {e}")

async def send_weekly_stats():
    logger.info("--- СБОР ЕЖЕНЕДЕЛЬНОЙ СТАТИСТИКИ ---")
    headers = login_5verst()
    if not headers or not VK_TOKEN: return
    
    bot = Bot(token=TOKEN)
    async with bot:
        tg_count = await bot.get_chat_member_count(int(TARGET_CHAT_ID))
        vk_resp = requests.get("https://api.vk.com/method/groups.getMembers", 
                               params={"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "count": 0}).json()
        vk_count = vk_resp.get("response", {}).get("count", 0)

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        offset = (now.weekday() - 5) % 7
        last_sat_dt = now - timedelta(days=offset)
        last_sat_str = last_sat_dt.strftime("%d.%m.%Y")
        
        count_finish, _, _ = get_results_data(last_sat_dt.strftime("%Y-%m-%d"))
        
        v_resp = requests.post("https://nrms.5verst.ru/api/v1/event/volunteer/list", 
                               json={"event_id": EVENT_ID, "event_date": last_sat_str}, headers=headers).json()
        v_list = v_resp.get("result", {}).get("volunteer_list", [])
        vol_count = len(set([v.get("full_name") for v in v_list]))

        msg = (f"📈 <b>ИТОГИ НЕДЕЛИ | КСТОВО</b>\n\n"
               f"👥 <b>Сообщество:</b>\n"
               f"• Telegram: <b>{tg_count}</b>\n"
               f"• ВКонтакте: <b>{vk_count}</b>\n\n"
               f"🏃‍♂️ <b>Последний старт:</b>\n"
               f"• Финишировало: <b>{count_finish}</b>\n"
               f"• Волонтеров: <b>{vol_count}</b>\n\n"
               f"🧡 Увидимся на 5 вёрст 🧡!")
        
        chat_id = ORGS_CHAT_ID if ORGS_CHAT_ID else TARGET_CHAT_ID
        await bot.send_message(int(chat_id), text=msg, parse_mode=ParseMode.HTML)

async def send_weather():
    lat, lon = 56.15, 44.20
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&timezone=Europe%2FMoscow"
    try:
        r = requests.get(url).json().get("current", {})
        temp = r.get("temperature_2m")
        msg = f"<b>Погода на старт:</b> {temp}°C. Хорошей пробежки! 🏃‍♂️"
        async with Bot(token=TOKEN) as bot:
            await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
    except: pass

async def main():
    if len(sys.argv) < 2: return
    mode = sys.argv[1]
    if mode == "--titles": await update_titles()
    elif mode == "--birthdays": await check_birthdays("day")
    elif mode == "--birthdays-month": await check_birthdays("month")
    elif mode == "--birthdays-week": await check_birthdays("week")
    elif mode == "--weather": await send_weather()
    elif mode == "--results": await send_results()
    elif mode == "--vk-check": await check_new_vk_members()
    elif mode == "--stats": await send_weekly_stats()
    elif mode == "--vk-update": await update_vk_status()
    elif mode == "--birthdays-auto":
        await check_birthdays("day")
        now = datetime.now(pytz.timezone(TIMEZONE))
        if now.day == 1: await check_birthdays("month")
        if now.weekday() == 0: await check_birthdays("week")

if __name__ == "__main__":
    asyncio.run(main())
