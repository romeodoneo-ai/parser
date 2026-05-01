"""
Парсер заданий YouDo.com — категория "Разработка ПО".
Опрашивает API раз в минуту, возвращает только новые задания.
"""

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

# Подкатегории раздела "Разработка ПО"
IT_SUB_IDS = [148, 146, 62, 63, 244, 245, 147, 246, 108]

SETTING_MAX_ID = "youdo_last_max_id"


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


async def fetch_new_tasks() -> List[Dict]:
    """
    Возвращает список {'task_id': str, 'text': str} для новых заданий.
    Использует максимальный ID задачи как метку времени — всё что выше → новое.
    При первом запуске только запоминает текущий максимум без отправки.
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

            try:
                items = data["ResultObject"]["Items"]
            except (KeyError, TypeError):
                logger.warning("YouDo: неожиданная структура ответа")
                return []

            if not items:
                logger.debug("YouDo: список пуст")
                return []

            # ID задач — целые числа, большее = новее
            ids = [int(item["Id"]) for item in items if item.get("Id")]
            if not ids:
                return []
            current_max = max(ids)

            last_max = int(storage.get_setting(SETTING_MAX_ID, "0"))

            # Первый запуск — запоминаем максимум и ничего не шлём
            if last_max == 0:
                storage.set_setting(SETTING_MAX_ID, str(current_max))
                logger.info(f"YouDo: первый запуск, запомнили max_id={current_max}")
                return []

            # Обычный запуск — шлём только задачи новее last_max
            new_items = [item for item in items if int(item.get("Id", 0)) > last_max]

            if not new_items:
                logger.info("YouDo: новых заданий нет")
                return []

            logger.info(f"YouDo: {len(new_items)} новых заданий (id > {last_max})")
            storage.set_setting(SETTING_MAX_ID, str(current_max))

            new_tasks = []
            for item in new_items:
                task_id = str(item["Id"])
                title = (item.get("Name") or "Без названия").strip()
                price = _format_price(item)
                url = item.get("Url", "")
                if url and not url.startswith("http"):
                    url = f"https://youdo.com{url}"

                description = await _fetch_description(session, task_id)
                text = _format_notification(title, description, price, url)
                new_tasks.append({"task_id": task_id, "text": text})

            return new_tasks

    except Exception as e:
        logger.error(f"YouDo ошибка: {e}")
        return []
