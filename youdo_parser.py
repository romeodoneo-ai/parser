"""
Парсер заданий YouDo.com — категория "Разработка ПО".
Первый запуск: все задачи за последние 3 дня от старых к новым.
Далее: каждую минуту только новые.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import aiohttp

import storage

logger = logging.getLogger(__name__)

API_URL = "https://youdo.com/api/tasks/tasks/"
TASK_URL = "https://youdo.com/api/tasks/task/{}/"

# Cookie подгружается из config.yaml → youdo.cookie
_cookie: str = ""

def set_cookie(cookie: str):
    global _cookie
    _cookie = cookie

def _make_headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "X-FeatureSetId": "893",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://youdo.com/tasks-all-opened-all",
        "Origin": "https://youdo.com",
    }
    if _cookie:
        h["Cookie"] = _cookie
    return h

IT_SUB_IDS = [148, 146, 62, 63, 244, 245, 147, 246, 108]

SETTING_MAX_ID = "youdo_last_max_id"
SETTING_INIT   = "youdo_initialized"

MAX_INIT_PAGES = 6  # страниц на первый запуск (~300 задач)
DAYS_BACK = 3       # фильтр по дате создания

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def _parse_date(date_str: str) -> Optional[datetime]:
    """
    Парсит YouDo DateTimeString:
      "30 апреля, 12:00"  →  datetime(2026, 4, 30, 12, 0)
      "сегодня, 18:41"    →  сегодня в 18:41
      "вчера, 12:00"      →  вчера в 12:00
      "Начать 1 мая, 00:00" → May 1
    """
    if not date_str:
        return None
    s = date_str.strip().lower()
    # убираем "начать" и подобные префиксы
    for prefix in ("начать ", "начало ", "до "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    now = datetime.now()
    try:
        if "сегодня" in s:
            time_part = s.split(",")[-1].strip()
            h, m = map(int, time_part.split(":"))
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
        if "вчера" in s:
            time_part = s.split(",")[-1].strip()
            h, m = map(int, time_part.split(":"))
            d = now - timedelta(days=1)
            return d.replace(hour=h, minute=m, second=0, microsecond=0)
        # "30 апреля, 12:00"
        parts = s.split(",")
        date_part = parts[0].strip()
        time_part = parts[-1].strip() if len(parts) > 1 else "00:00"
        tokens = date_part.split()
        if len(tokens) >= 2:
            day = int(tokens[0])
            month = MONTHS_RU.get(tokens[1], 0)
            if month:
                h, m = map(int, time_part.split(":"))
                year = now.year
                # если месяц впереди текущего — это прошлый год
                if month > now.month:
                    year -= 1
                return datetime(year, month, day, h, m)
    except Exception:
        pass
    return None


def _is_within_days(date_str: str, days: int) -> bool:
    dt = _parse_date(date_str)
    if dt is None:
        return True  # если не распарсили — не отбрасываем
    cutoff = datetime.now() - timedelta(days=days)
    return dt >= cutoff


def _format_price(item: Dict) -> str:
    budget = (item.get("BudgetDescription") or "").strip()
    if budget:
        return budget + " ₽"
    return "Договорная"


def _format_notification(title: str, description: str, price: str, url: str, date_str: str) -> str:
    lines = ["🛠 **Новый заказ на YouDo**", ""]
    lines.append(f"💼 {title}")
    if date_str:
        lines.append(f"📅 {date_str}")
    if description:
        if len(description) > 500:
            description = description[:500] + "…"
        lines.append(f"\n📝 {description}")
    lines.append(f"\n💰 {price}")
    lines.append(f"🔗 {url}")
    return "\n".join(lines)


async def _fetch_detail(session: aiohttp.ClientSession, task_id: str) -> dict:
    """Возвращает {'description': str, 'created': datetime | None}."""
    try:
        async with session.get(
            TASK_URL.format(task_id),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json(content_type=None)
            task_data = data.get("ResultObject", {}).get("TaskData", {})
            dates = task_data.get("Dates", {})
            created = None
            ts_ms = dates.get("CreationDate")
            if ts_ms:
                try:
                    created = datetime.fromtimestamp(int(ts_ms) / 1000)
                except Exception:
                    pass
            return {
                "description": (task_data.get("Description") or "").strip(),
                "created": created,
            }
    except Exception:
        return {}


async def _fetch_page(session: aiohttp.ClientSession, page: int) -> List[Dict]:
    payload = {
        "q": "", "list": "all", "status": "opened",
        "sortType": 1, "page": page,
        "lat": 55.755864, "lng": 37.617698,
        "noOffers": False, "onlySbr": False, "onlyB2B": False,
        "onlyVacancies": False, "onlyVirtual": False, "priceMin": "",
        "sub": IT_SUB_IDS,
        "searchRequestId": str(uuid.uuid4()),
    }
    try:
        async with session.post(
            API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)
            return data["ResultObject"]["Items"]
    except Exception:
        return []


async def _build_task(session: aiohttp.ClientSession, item: Dict) -> Dict:
    task_id = str(item["Id"])
    title = (item.get("Name") or "Без названия").strip()
    price = _format_price(item)
    date_str = item.get("DateTimeString", "")
    url = item.get("Url", "")
    if url and not url.startswith("http"):
        url = f"https://youdo.com{url}"
    detail = await _fetch_detail(session, task_id)
    return {
        "task_id": task_id,
        "created": detail.get("created"),
        "text": _format_notification(title, detail.get("description", ""), price, url, date_str),
    }


async def fetch_new_tasks() -> List[Dict]:
    """
    Первый вызов: все задачи за DAYS_BACK дней, от старых к новым.
    Последующие: только задачи с ID выше последнего виденного.
    """
    initialized = storage.get_setting(SETTING_INIT, "0") == "1"
    last_max_id = int(storage.get_setting(SETTING_MAX_ID, "0"))

    try:
        async with aiohttp.ClientSession(headers=_make_headers()) as session:

            if not initialized:
                all_items: List[Dict] = []
                for page in range(1, MAX_INIT_PAGES + 1):
                    items = await _fetch_page(session, page)
                    if not items:
                        break
                    all_items.extend(items)
                    if len(items) < 50:
                        break
                    await asyncio.sleep(0.3)

                storage.set_setting(SETTING_INIT, "1")

                if not all_items:
                    return []

                # фиксируем текущий максимальный ID
                new_max = max(int(i.get("Id") or 0) for i in all_items)
                storage.set_setting(SETTING_MAX_ID, str(new_max))

                logger.info(f"YouDo: первый запуск, {len(all_items)} задач со списка, загружаю детали...")

                # параллельная загрузка деталей пачками по 10
                sem = asyncio.Semaphore(10)
                async def fetch_with_sem(item):
                    async with sem:
                        return await _build_task(session, item)

                tasks_built = await asyncio.gather(*[fetch_with_sem(i) for i in all_items])

                # фильтруем по дате создания (последние DAYS_BACK дней)
                cutoff = datetime.now() - timedelta(days=DAYS_BACK)
                fresh = []
                for t in tasks_built:
                    created = t.get("created")
                    if created is None or created >= cutoff:
                        fresh.append(t)

                # от старых к новым
                fresh.sort(key=lambda t: t.get("created") or datetime.min)

                logger.info(f"YouDo: {len(fresh)} задач за последние {DAYS_BACK} дня (из {len(all_items)})")
                return fresh

            else:
                items = await _fetch_page(session, 1)
                if not items:
                    logger.info("YouDo: новых заданий нет")
                    return []

                new_items = [i for i in items if int(i.get("Id") or 0) > last_max_id]
                if not new_items:
                    logger.info("YouDo: новых заданий нет")
                    return []

                new_max = max(int(i.get("Id") or 0) for i in new_items)
                storage.set_setting(SETTING_MAX_ID, str(new_max))

                logger.info(f"YouDo: {len(new_items)} новых заданий")
                result = []
                for item in new_items:
                    result.append(await _build_task(session, item))
                return result

    except Exception as e:
        logger.error(f"YouDo ошибка: {e}")
        return []
