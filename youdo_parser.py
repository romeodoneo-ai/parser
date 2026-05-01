"""
Парсер заданий YouDo.com — категория "Разработка ПО".
Опрашивает API раз в минуту, возвращает только новые задания.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import aiohttp

import storage

logger = logging.getLogger(__name__)

API_URL = "https://youdo.com/api/tasks/tasks/"
TASK_URL = "https://youdo.com/api/tasks/task/{}/"

HEADERS = {
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

# Подкатегории раздела "Разработка ПО"
IT_SUB_IDS = [148, 146, 62, 63, 244, 245, 147, 246, 108]

# Задания старше этого порога не отправляем
MAX_AGE_HOURS = 6

_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def _parse_date(s: str) -> Optional[datetime]:
    """Парсит строку вида '30 апреля, 12:00'."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+(\w+),\s+(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    day, month_str, hour, minute = m.groups()
    month = _MONTHS_RU.get(month_str.lower())
    if not month:
        return None
    now = datetime.now()
    try:
        dt = datetime(now.year, month, int(day), int(hour), int(minute))
        # Если дата оказалась в будущем — скорее всего прошлый год
        if dt > now + timedelta(hours=1):
            dt = dt.replace(year=now.year - 1)
        return dt
    except ValueError:
        return None


def _is_fresh(item: Dict) -> bool:
    dt = _parse_date(item.get("DateTimeString", ""))
    if dt is None:
        return True  # не можем определить — пропускаем
    return datetime.now() - dt <= timedelta(hours=MAX_AGE_HOURS)


def _format_price(item: Dict) -> str:
    budget = (item.get("BudgetDescription") or "").strip()
    if budget:
        return budget + " ₽"
    return "Договорная"


def _format_notification(title: str, description: str, price: str, url: str) -> str:
    lines = ["🛠 **Новый заказ на YouDo**", ""]
    lines.append(f"💼 {title}")
    if description:
        if len(description) > 500:
            description = description[:500] + "…"
        lines.append(f"\n📝 {description}")
    lines.append(f"\n💰 {price}")
    lines.append(f"🔗 {url}")
    return "\n".join(lines)


async def _fetch_description(session: aiohttp.ClientSession, task_id: str) -> str:
    """Загружает описание задачи с детальной страницы."""
    try:
        async with session.get(
            TASK_URL.format(task_id),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json(content_type=None)
            return (
                data.get("ResultObject", {})
                    .get("TaskData", {})
                    .get("Description", "")
                or ""
            ).strip()
    except Exception:
        return ""


async def fetch_new_tasks() -> List[Dict]:
    """
    Возвращает список {'task_id': str, 'text': str} для новых заданий.
    При первом вызове (пустая таблица) только засевает ID без отправки.
    """
    payload = {
        "q": "",
        "list": "all",
        "status": "opened",
        "sortType": 1,
        "page": 1,
        "noOffers": False,
        "onlySbr": False,
        "onlyB2B": False,
        "onlyVacancies": False,
        "onlyVirtual": False,
        "priceMin": "",
        "sub": IT_SUB_IDS,
        "searchRequestId": str(uuid.uuid4()),
    }

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.post(
                API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"YouDo API вернул {resp.status}")
                    return []
                data = await resp.json(content_type=None)

            items = []
            try:
                items = data["ResultObject"]["Items"]
            except (KeyError, TypeError):
                logger.warning("YouDo: неожиданная структура ответа")
                return []

            if not items:
                logger.debug("YouDo: список задач пуст")
                return []

            new_tasks = []
            for item in items:
                task_id = str(item.get("Id", ""))
                if not task_id:
                    continue
                if storage.is_youdo_seen(task_id):
                    continue

                storage.mark_youdo_seen(task_id)

                if not _is_fresh(item):
                    continue

                title = (item.get("Name") or "Без названия").strip()
                price = _format_price(item)
                url = item.get("Url", "")
                if url and not url.startswith("http"):
                    url = f"https://youdo.com{url}"

                description = await _fetch_description(session, task_id)

                text = _format_notification(title, description, price, url)
                new_tasks.append({"task_id": task_id, "text": text})

            if new_tasks:
                logger.info(f"YouDo: {len(new_tasks)} новых заданий")
            else:
                logger.debug("YouDo: новых заданий нет")

            return new_tasks

    except Exception as e:
        logger.error(f"YouDo ошибка: {e}")
        return []
