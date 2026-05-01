"""
Парсер заданий YouDo.com — айти-категории.
Опрашивает API каждый вызов, возвращает только новые задания.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

import storage

logger = logging.getLogger(__name__)

API_URL = "https://youdo.com/api/tasks/tasks/"

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

# Побитовые флаги IT-категорий
IT_FLAGS = (
    4194304  # Разработка ПО
    | 262144  # Компьютерная помощь
    | 1048576  # Виртуальный помощник
    | 512     # Дизайн
)

# Игнорируем задания старше этого времени
MAX_AGE_HOURS = 6


def _is_it_task(item: dict) -> bool:
    flag = item.get("CategoryFlag", 0)
    return bool(flag & IT_FLAGS)


def _parse_date(item: dict) -> Optional[datetime]:
    """Пробуем разные поля с датой."""
    for field in ("DateCreate", "DateTimeString", "Date", "CreateDate"):
        raw = item.get(field)
        if not raw:
            continue
        try:
            # Убираем 'Z' или временну́ю зону для единообразия
            raw = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(raw)
        except (ValueError, AttributeError):
            continue
    return None


def _is_fresh(item: dict) -> bool:
    dt = _parse_date(item)
    if dt is None:
        return True  # если дата не парсится — пропускаем фильтр
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    return dt >= cutoff


def _format_price(item: dict) -> str:
    amount = item.get("PriceAmount") or item.get("MaxPrice")
    payment_type = item.get("PaymentType")
    if payment_type == 2 or not amount:
        return "Договорная"
    return f"до {int(amount):,} ₽".replace(",", " ")


def _format_notification(item: dict) -> str:
    title = item.get("Name", "").strip()
    description = item.get("Description", "").strip()
    if len(description) > 400:
        description = description[:400] + "…"
    price = _format_price(item)
    url = item.get("Url", "")
    if url and not url.startswith("http"):
        url = f"https://youdo.com{url}"

    lines = ["🛠 **Новый заказ на YouDo**", ""]
    if title:
        lines.append(f"💼 {title}")
    if description:
        lines.append(f"\n📝 {description}")
    lines.append(f"\n💰 {price}")
    if url:
        lines.append(f"🔗 {url}")
    return "\n".join(lines)


async def fetch_new_tasks() -> list[dict]:
    """
    Делает запрос к YouDo API и возвращает список словарей:
    {'task_id': str, 'text': str}
    для каждого нового айти-задания.
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
        "searchRequestId": str(uuid.uuid4()),
    }

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.post(API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"YouDo API вернул {resp.status}")
                    return []
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"Ошибка запроса к YouDo: {e}")
        return []

    items = []
    try:
        items = data["ResultObject"]["Items"]
    except (KeyError, TypeError):
        logger.warning(f"Неожиданная структура ответа YouDo: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return []

    new_tasks = []
    for item in items:
        task_id = str(item.get("Id", ""))
        if not task_id:
            continue
        if not _is_it_task(item):
            continue
        if not _is_fresh(item):
            continue
        if storage.is_youdo_seen(task_id):
            continue

        storage.mark_youdo_seen(task_id)
        new_tasks.append({"task_id": task_id, "text": _format_notification(item)})

    if new_tasks:
        logger.info(f"YouDo: найдено {len(new_tasks)} новых IT-заданий")
    else:
        logger.debug("YouDo: новых IT-заданий нет")

    return new_tasks
