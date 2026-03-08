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
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
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
FLUD_THREAD_ID = os.getenv("FLUD_THREAD_ID")
THREAD_ID = int(THREAD_ID_ENV) if THREAD_ID_ENV and THREAD_ID_ENV.strip() else None

# Настройки для Кстово Юбилейный
EVENT_ID = 10079
VK_GROUP_ID = 231094435
VK_TOKEN = os.getenv("VK_TOKEN")

# ========================= ВСПОМОГАТЕЛЬНОЕ =========================
def extract_id(input_str):
    s = str(input_str).strip()
    if not s or s.lower() == 'nan':
        return None
    digits = re.sub(r"\D", "", s)
    return digits if digits else None


def login_5verst():
    try:
        r = requests.post(
            "https://nrms.5verst.ru/api/v1/auth/login",
            json={"username": NRMS_USERNAME, "password": NRMS_PASSWORD},
            timeout=15
        )
        r.raise_for_status()
        token = r.json().get("result", {}).get("token")
        if token:
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        return None
    except Exception as e:
        logger.error(f"Ошибка авторизации NRMS: {e}")
        return None

# ========================= ЛОГИКА ПОГОДЫ =========================
async def send_weather_forecast():
    # Координаты парка Юбилейный (Кстово)
    lat, lon = 56.1611, 44.2182
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation_probability,weathercode&forecast_days=1&timezone={TIMEZONE}"
    
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        times = data['hourly']['time']
        now_tz = datetime.now(pytz.timezone(TIMEZONE))
        target_hour = now_tz.replace(hour=9, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        
        try:
            idx = times.index(target_hour)
        except:
            idx = 9

        temp = data['hourly']['temperature_2m'][idx]
        prob = data['hourly']['precipitation_probability'][idx]
        code = data['hourly']['weathercode'][idx]

        weather_map = {
            0: "Ясно ☀️", 1: "Преимущественно ясно 🌤", 2: "Переменная облачность ⛅️", 3: "Пасмурно ☁️",
            45: "Туман 🌫", 51: "Морось 🌦", 61: "Небольшой дождь 🌧", 63: "Дождь ☔️",
            71: "Снег ❄️", 73: "Снегопад ❄️❄️", 80: "Ливневый дождь ⛈"
        }
        status = weather_map.get(code, "Облачно")

        msg = (
            f"🌳 <b>Погода на старте в 09:00:</b>\n\n"
            f"🌡 Температура: <b>{temp}°C</b>\n"
            f"☁️ На улице: <b>{status}</b>\n"
            f"☔️ Вероятность осадков: <b>{prob}%</b>\n\n"
            f"Одевайтесь по погоде! Ждем вас в Юбилейном! 🧡"
        )

        bot = Bot(token=TOKEN)
        async with bot:
            await bot.send_message(
                int(TARGET_CHAT_ID),
                text=msg,
                parse_mode=ParseMode.HTML,
                message_thread_id=THREAD_ID
            )
            logger.info("Прогноз погоды отправлен.")
    except Exception as e:
        logger.error(f"Ошибка получения погоды: {e}")

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
        requests.get(
            "https://api.vk.com/method/status.set",
            params={"group_id": VK_GROUP_ID, "text": status_text, "access_token": VK_TOKEN, "v": "5.131"}
        )

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
            logger.info(f"Дата мероприятия ВК обновлена на {date_str} (08:40 - 10:00)")

    except Exception as e:
        logger.error(f"Ошибка ВК API: {e}")

# ========================= ЛОГИКА ТИТУЛОВ =========================
async def update_titles(is_manual=False):
    logger.info("--- ОБНОВЛЕНИЕ ТИТУЛОВ ---")
    FLUD_THREAD_ID = os.getenv("FLUD_THREAD_ID")

    # 1. Загружаем кэш
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            full_cache = json.load(f)
    else:
        full_cache = {str(TARGET_CHAT_ID): {}}

    chat_cache = full_cache.get(str(TARGET_CHAT_ID), {})
    
    # Списки для работы
    to_notify = []  # Только те, кого РЕАЛЬНО нет в кэше
    to_process = [] # Все, кому будем обновлять титулы
    
    # 2. Читаем таблицу
    try:
        res_form = requests.get(SHEET_FORM_URL, timeout=20)
        df_form = pd.read_csv(StringIO(res_form.text), encoding="utf-8")
        
        # Убираем дубликаты по TG ID из таблицы, оставляя последние записи
        df_form = df_form.drop_duplicates(subset=[df_form.columns[1]], keep='last')
        
        temp_bot = Bot(token=TOKEN)
        
        for _, row in df_form.iterrows():
            f_tg_id = str(extract_id(row.iloc[1]))
            f_v5_id = str(extract_id(row.iloc[2]))
            
            if not f_tg_id or not f_v5_id:
                continue

            # Проверяем: новый ли это человек для бота?
            is_new = f_tg_id not in chat_cache
            
            # Если новый ИЛИ мы запустили вручную — готовим к обработке
            if is_new or is_manual:
                try:
                    member = await temp_bot.get_chat_member(chat_id=int(TARGET_CHAT_ID), user_id=int(f_tg_id))
                    u = member.user
                    name = f"{u.first_name or 'Участник'}{f' {u.last_name}' if u.last_name else ''}"
                    user_label = f"<a href='tg://user?id={f_tg_id}'>{name}</a>{f' (@{u.username})' if u.username else ''}"
                except:
                    user_label = f"Участник (ID: {f_tg_id})"

                person_data = {"tg_id": f_tg_id, "v5_id": f_v5_id, "label": user_label}
                to_process.append(person_data)
                
                if is_new:
                    to_notify.append(f"• {user_label} (ID: {f_v5_id})")
                
                # Сразу помечаем в кэше, чтобы не спамить в следующий раз
                chat_cache[f_tg_id] = int(f_v5_id)

    except Exception as e:
        logger.error(f"Ошибка парсинга таблицы: {e}")

    # 3. Сохраняем обновленный кэш
    full_cache[str(TARGET_CHAT_ID)] = chat_cache
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(full_cache, f, indent=2, ensure_ascii=False)

    # 4. Отправляем уведомление, если есть новички
    async with Bot(token=TOKEN) as bot:
        if to_notify:
            msg = "⚡️ <b>Новая регистрация в ЛК!</b>\n\n" + "\n".join(to_notify) + "\n\n<i>Бот приступает к обновлению титулов...</i>"
            try:
                target_thread = int(FLUD_THREAD_ID) if FLUD_THREAD_ID else THREAD_ID
                await bot.send_message(chat_id=int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=target_thread)
            except Exception as e:
                logger.error(f"Ошибка уведомления: {e}")

        # 5. Цикл NRMS и Титулов
        headers = login_5verst()
        if not headers or not to_process:
            return

        for p in to_process:
            try:
                # Запрос к NRMS
                r = requests.post("https://nrms.5verst.ru/api/v1/website/athlete/statById", json={"id": p['v5_id']}, headers=headers, timeout=15)
                res = r.json().get("result")
                if not res: continue

                m = res.get("personal_best", {}).get("club_membership", {})
                run_map = {"run500": "500", "run250": "250", "run100": "100", "run50": "50", "run25": "25", "run10": "10"}
                vol_map = {"vol500": "500", "vol250": "250", "vol100": "100", "vol50": "50", "vol25": "25", "vol10": "10"}
                
                run_badge = run_map.get(m.get("run"), "")
                vol_badge = vol_map.get(m.get("volunteer"), "")

                badges = [b for b in [run_badge, vol_badge] if b]
                # ФИКС: Если нет клубов — строго "Новичок"
                title = f"Клуб {'|'.join(badges)}" if badges else "Новичок"

                uid = int(p['tg_id'])
                
                # Проверка прав (не трогаем создателя)
                member = await bot.get_chat_member(chat_id=TARGET_CHAT_ID, user_id=uid)
                if member.status == 'creator':
                    continue

                # Даем права админа и ставим титул
                try:
                    await bot.promote_chat_member(chat_id=int(TARGET_CHAT_ID), user_id=uid, can_manage_chat=True)
                    await bot.set_chat_administrator_custom_title(chat_id=int(TARGET_CHAT_ID), user_id=uid, custom_title=title)
                    logger.info(f"Титул '{title}' установлен для {uid}")
                except Exception as ex:
                    logger.warning(f"Ошибка TG для {uid}: {ex}")

                # ПАУЗА 3 секунды, чтобы Telegram не ругался (Flood Control)
                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Общая ошибка для {p['tg_id']}: {e}")
        # 5. Если запуск ручной — выводим отчет
        if is_manual and all_processed_people:
            report = "📊 <b>Финальный отчет по титулам:</b>\n\n" + "\n".join([f"• {p['link']} — обновлен" for p in all_processed_people])
            await bot.send_message(chat_id=int(TARGET_CHAT_ID), text=report, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
# ========================= КНОПКА ЛК =========================
async def send_profile_button():
    bot = Bot(token=TOKEN)
    # Прямая ссылка на Web App твоего бота
    bot_username = "verstkstovo_bot" 
    url = f"https://t.me/{bot_username}/app"
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(text="Мой профиль 🧡", url=url)
    ]])
    
    text = (
        "🧡 <b>Личный кабинет участника</b>\n\n"
        "Настрой автоматическое обновление своих титулов прямо здесь!\n\n"
        "1️⃣ Нажми кнопку <b>«Мой профиль»</b>\n"
        "2️⃣ Укажи свой <b>ID 5 вёрст</b>\n"
        "3️⃣ Бот сам обновит твой клубный титул в этом чате.\n\n"
        "<i>Титулы обновляются несколько раз в неделю по расписанию.</i>"
    )
    
    async with bot:
        await bot.send_message(
            chat_id=int(TARGET_CHAT_ID),
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            message_thread_id=THREAD_ID
        )
        logger.info("Кнопка профиля (Web App Link) отправлена в чат.")
# ========================= ЛОГИКА РЕЗУЛЬТАТОВ =========================
def get_results_data(date_str):
    url_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    url = f"https://5verst.ru/kstovoyubileyniy/results/{url_date}/"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, timeout=20, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.select("table.sortable tbody tr")
            real_finishers = 0
            for row in rows:
                cells = row.find_all("td")
                if cells and cells[0].get_text(strip=True).isdigit():
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
    if not VK_TOKEN:
        return album_url, None
    try:
        day, month, _ = display_date.split('.')
        date_pattern = f"{day}{month}"
        p = {"owner_id": -VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131"}
        resp = requests.get("https://api.vk.com/method/photos.getAlbums", params=p).json()
        albums = resp.get("response", {}).get("items", [])
        target = next((a for a in albums if date_pattern in re.sub(r'\D', '', a.get('title', ''))), None)
        if not target and run_num:
            target = next((a for a in albums if f"#{run_num}" in a.get('title', '')), None)
        if not target and albums:
            target = albums[0]
        if target:
            album_url = f"https://vk.com/album-{VK_GROUP_ID}_{target['id']}"
            p_img = {"owner_id": -VK_GROUP_ID, "album_id": target['id'], "access_token": VK_TOKEN, "v": "5.131", "count": 1}
            photos = requests.get("https://api.vk.com/method/photos.get", params=p_img).json().get("response", {}).get("items", [])
            if photos:
                return album_url, sorted(photos[0].get("sizes", []), key=lambda x: x['width'])[-1]['url']
    except:
        pass
    return album_url, None


async def send_results():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    offset = (now.weekday() - 5) % 7
    last_sat = now - timedelta(days=offset)
    date_str, disp_date = last_sat.strftime("%Y-%m-%d"), last_sat.strftime("%d.%m.%Y")

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            if f.read().strip() == disp_date:
                return

    count, web_url, run_num = get_results_data(date_str)
    if count == 0:
        logger.info(f"Результаты за {disp_date} еще не опубликованы.")
        return

    headers = login_5verst()
    vols_text = ""
    if headers:
        try:
            r = requests.post(
                "https://nrms.5verst.ru/api/v1/event/volunteer/list",
                json={"event_id": EVENT_ID, "event_date": disp_date},
                headers=headers
            )
            v_list = r.json().get("result", {}).get("volunteer_list", [])
            if v_list:
                vols = {}
                for v in v_list:
                    n, rn = v.get("full_name"), v.get("role_name")
                    vols[n] = vols.get(n, []) + [rn]
                vols_text = f"\n🧡 <b>Команда героев ({len(vols)}):</b>\n" + \
                            "\n".join([f"• <b>{name}</b> — <i>{', '.join(roles)}</i>" for name, roles in vols.items()])
        except:
            pass

    alb_url, img_url = get_vk_photo(disp_date, run_num)
    msg = (
        f"🌳 <b>5 вёрст парк Юбилейный | Кстово</b>\n"
        f"🗓 <b>Старт от {disp_date}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏁 Финишировало: <b>{count}</b>\n"
        f"{vols_text}\n\n"
        f"📊 <a href='{web_url}'>Протокол</a>\n"
        f"📸 <a href='{alb_url}'>Фотографии</a>"
    )

    bot = Bot(token=TOKEN)
    async with bot:
        try:
            if img_url:
                await bot.send_photo(int(TARGET_CHAT_ID), photo=img_url, caption=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            else:
                await bot.send_message(int(TARGET_CHAT_ID), text=msg, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(disp_date)
            git_push()
            await update_vk_status()
        except Exception as e:
            logger.error(f"Ошибка отправки результатов: {e}")


def git_push():
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Action Bot"])
        subprocess.run(["git", "config", "user.email", "actions@github.com"])
        subprocess.run(["git", "add", LOG_FILE, VK_MEMBERS_FILE, CACHE_FILE])
        subprocess.run(["git", "commit", "-m", "Auto: Sync logs and cache"])
        subprocess.run(["git", "push"])
    except:
        pass


# ========================= ДНИ РОЖДЕНИЯ =========================
async def check_birthdays(mode="day"):
    if not SHEET_BIRTHDAYS_URL:
        return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    try:
        res = requests.get(SHEET_BIRTHDAYS_URL, timeout=30)
        res.encoding = 'utf-8'
        df = pd.read_csv(StringIO(res.text), encoding='utf-8', dtype=str).fillna("")
    except Exception as e:
        logger.error(f"Ошибка загрузки таблицы ДР: {e}")
        return

    congrats, report_list = [], []
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)

    for _, row in df.iterrows():
        try:
            name = str(row.get('name', '')).strip()
            bd_val = str(row.get('birthday', '')).strip().replace('/', '.').replace('-', '.')
            username = str(row.get('username', '')).strip().lstrip('@')
            if not name or '.' not in bd_val: continue
            parts = bd_val.split('.')
            d_t, m_t = int(float(parts[0])), int(float(parts[1]))
            mention = f"{name} (@{username})" if (username and username.lower() != "nan") else name

            if mode == "day" and d_t == now.day and m_t == now.month:
                congrats.append(f"<b>{mention}</b>")
            else:
                line = f"• {d_t:02d}.{m_t:02d} — <b>{mention}</b>"
                if mode == "month" and m_t == now.month: report_list.append(line)
                elif mode == "week":
                    bd_this_year = datetime(now.year, m_t, d_t, tzinfo=tz)
                    if monday <= bd_this_year <= sunday: report_list.append(line)
        except: continue

    if not (congrats or report_list): return
    bot = Bot(token=TOKEN)
    async with bot:
        text = ""
        if mode == "month" and report_list: text = f"🎂 <b>Именинники месяца:</b>\n\n" + "\n".join(sorted(report_list))
        elif mode == "week" and report_list: text = f"📅 <b>Дни рождения на неделе:</b>\n\n" + "\n".join(sorted(report_list))
        elif mode == "day" and congrats: text = f"🌟 <b>СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!</b> 🌟\n\n" + "\n".join(congrats)
        if text: await bot.send_message(int(TARGET_CHAT_ID), text=text, parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)


# ========================= ВК МОНИТОРИНГ =========================
async def check_new_vk_members():
    if not VK_TOKEN: return
    try:
        p = {"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "fields": "first_name,last_name"}
        resp = requests.get("https://api.vk.com/method/groups.getMembers", params=p).json()
        current_members = resp.get("response", {}).get("items", [])
        total_count = resp.get("response", {}).get("count", 0)

        old_ids = set(json.load(open(VK_MEMBERS_FILE, "r")) if os.path.exists(VK_MEMBERS_FILE) else [])
        new_names = [f"<a href='https://vk.com/id{m['id']}'>{m['first_name']} {m['last_name']}</a>" for m in current_members if m['id'] not in old_ids]

        if new_names:
            goals = [250, 500, 700, 1000, 1500, 2000, 5000]
            next_goal = next((g for g in goals if g > total_count), None)
            goal_text = f"\n\n📈 Нас уже <b>{total_count}</b>! " + (f"До цели {next_goal} осталось {next_goal - total_count} чел." if next_goal else "Мы превзошли все цели! 🔥")
            async with Bot(token=TOKEN) as bot:
                await bot.send_message(int(TARGET_CHAT_ID), text=f"⚡️ <b>Новый подписчик в ВК!</b>\n\n{', '.join(new_names)} 🎉{goal_text}", parse_mode=ParseMode.HTML, message_thread_id=THREAD_ID)

        json.dump([m['id'] for m in current_members], open(VK_MEMBERS_FILE, "w"))
        if new_names or not old_ids: git_push()
    except Exception as e:
        logger.error(f"Ошибка ВК мониторинга: {e}")


# ========================= ЕЖЕНЕДЕЛЬНЫЕ ИТОГИ =========================
async def send_weekly_stats():
    headers = login_5verst()
    if not headers or not VK_TOKEN: return
    bot = Bot(token=TOKEN)
    async with bot:
        tg_count = await bot.get_chat_member_count(int(TARGET_CHAT_ID))
        vk_r = requests.get("https://api.vk.com/method/groups.getMembers", params={"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.131", "count": 0}).json()
        vk_count = vk_r.get("response", {}).get("count", "???")

        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        last_sat_dt = now - timedelta(days=(now.weekday() - 5) % 7)
        last_sat_str = last_sat_dt.strftime("%d.%m.%Y")
        count_finish, _, _ = get_results_data(last_sat_dt.strftime("%Y-%m-%d"))

        msg = (f"📈 <b>ИТОГИ НЕДЕЛИ | КСТОВО</b>\n\n👥 <b>Сообщество:</b>\n• Telegram: <b>{tg_count}</b>\n• ВКонтакте: <b>{vk_count}</b>\n\n"
               f"🏃‍♂️ <b>Последний старт ({last_sat_str}):</b>\n• Финишировало: <b>{count_finish}</b>\n\n🧡 Увидимся на 5 вёрст 🧡!")
        if ORGS_CHAT_ID: await bot.send_message(int(ORGS_CHAT_ID), text=msg, parse_mode=ParseMode.HTML)


# ========================= ЗАПУСК =========================
async def main():
    if len(sys.argv) < 2:
        logger.info("Аргументы: --titles, --weather, --birthdays, --birthdays-month, --birthdays-week, --birthdays-auto, --results, --vk-check, --stats, --vk-update, --send-button")
        return

    m = sys.argv[1]
    if m == "--titles": await update_titles()
    elif m == "--weather": await send_weather_forecast()
    elif m == "--birthdays": await check_birthdays("day")
    elif m == "--birthdays-month": await check_birthdays("month")
    elif m == "--birthdays-week": await check_birthdays("week")
    elif m == "--results": await send_results()
    elif m == "--vk-check": await check_new_vk_members()
    elif m == "--stats": await send_weekly_stats()
    elif m == "--vk-update": await update_vk_status()
    elif m == "--send-button": await send_profile_button()
    elif m == "--birthdays-auto":
        await check_birthdays("day")
        today = datetime.now(pytz.timezone(TIMEZONE))
        if today.day == 1: await check_birthdays("month")
        if today.weekday() == 0: await check_birthdays("week")
    else: logger.warning(f"Неизвестная команда: {m}")

if __name__ == "__main__":
    asyncio.run(main())
