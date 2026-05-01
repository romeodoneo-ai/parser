"""
Парсер заданий YouDo.com — категория "Разработка ПО".
Первый запуск: все открытые задачи от старых к новым.
Далее: каждую минуту только новые.
"""

import asyncio
import logging
import uuid
from typing import List, Dict

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

IT_SUB_IDS = [148, 146, 62, 63, 244, 245, 147, 246, 108]

SETTING_MAX_ID = "youdo_last_max_id"
SETTING_INIT   = "youdo_initialized"


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


async def _fetch_page(session: aiohttp.ClientSession, page: int) -> List[Dict]:
    payload = {
        "q": "", "list": "all", "status": "opened",
        "sortType": 1, "page": page,
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
    url = item.get("Url", "")
    if url and not url.startswith("http"):
        url = f"https://youdo.com{url}"
    description = await _fetch_description(session, task_id)
    return {"task_id": task_id, "text": _format_notification(title, description, price, url)}


async def fetch_new_tasks() -> List[Dict]:
    """
    Первый вызов: возвращает ВСЕ открытые задачи (все страницы), от старых к новым.
    Последующие: только задачи с ID выше последнего виденного.
    """
    initialized = storage.get_setting(SETTING_INIT, "0") == "1"
    last_max_id = int(storage.get_setting(SETTING_MAX_ID, "0"))

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:

            if not initialized:
                # Собираем все страницы
                all_items: List[Dict] = []
                page = 1
                while True:
                    items = await _fetch_page(session, page)
                    if not items:
                        break
                    all_items.extend(items)
                    if len(items) < 50:
                        break
                    page += 1
                    await asyncio.sleep(0.5)

                if not all_items:
                    return []

                # Сортируем от старых к новым (ID возрастает)
                all_items.sort(key=lambda x: int(x.get("Id") or 0))
                new_max = int(all_items[-1].get("Id") or 0)

                storage.set_setting(SETTING_MAX_ID, str(new_max))
                storage.set_setting(SETTING_INIT, "1")

                logger.info(f"YouDo: первый запуск, загружено {len(all_items)} задач со всех страниц")

                result = []
                for item in all_items:
                    result.append(await _build_task(session, item))
                return result

            else:
                # Обычный режим — только страница 1, только новее last_max_id
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
