"""
Парсер YouDo.com.

Стратегия (по приоритету):
  1. Перехват XHR/fetch ответов через Playwright — JSON с полными данными задания.
  2. HTML-парсинг через Playwright — если JSON не поймали (только title+url).
  3. Прямой HTTP к API — если Playwright недоступен.

YouDo фильтрует задачи клиентски: API всегда отдаёт tasks/tasks/ без
параметра категории. Фильтрация происходит по полю CategoryFlag в ответе.

https://youdo.com/tasks-all-opened-all
"""

import re
import aiohttp
from bs4 import BeautifulSoup
from .base import BaseParser, HEADERS, logger

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# CategoryFlag значения для IT/разработки на YouDo.
# Логи покажут полный список — добавляйте сюда нужные.
IT_FLAGS = {
    "computerhelp",   # Компьютерная помощь / IT
    "computers",      # Компьютеры (возможный родительский флаг)
    "it",             # IT (возможный флаг)
    "programming",    # Программирование
    "webdesign",      # Веб-дизайн/разработка
    "development",    # Разработка
    "software",       # Разработка ПО
    "mobiledev",      # Мобильная разработка
    "web",            # Веб
    "1c",             # 1С
    "seo",            # SEO
}


class YoudoParser(BaseParser):
    name = "YouDo"
    base_url = "https://youdo.com"

    async def get_tasks(self, session, url: str) -> list:
        if PLAYWRIGHT_OK:
            tasks = await self._fetch_via_playwright(url)
            if tasks:
                logger.info(f"[YouDo] Найдено через Playwright: {len(tasks)}")
                return tasks
            logger.warning("[YouDo] Playwright вернул 0 задач — пробуем HTTP.")

        tasks = await self._fetch_via_http(session, url)
        logger.info(f"[YouDo] Найдено через HTTP: {len(tasks)}")
        return tasks

    async def _fetch_via_playwright(self, url: str) -> list:
        captured_tasks = []
        html = ""

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="ru-RU",
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()

                async def on_response(response):
                    if response.status != 200:
                        return
                    if "youdo.com/api/tasks/tasks" not in response.url:
                        return
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    try:
                        data = await response.json()
                        raw = self._raw_candidates(data)
                        if not raw:
                            return
                        # Логируем все уникальные CategoryFlag для диагностики
                        all_flags = sorted({
                            str(item.get("CategoryFlag") or "")
                            for item in raw if isinstance(item, dict)
                        } - {""})
                        logger.info(
                            f"[YouDo] API {response.url} → {len(raw)} задач | "
                            f"все CategoryFlag: {all_flags}"
                        )
                        found = self._extract_from_json(data)
                        logger.info(f"[YouDo] После IT-фильтра: {len(found)} задач")
                        if found:
                            captured_tasks.extend(found)
                    except Exception as e:
                        logger.debug(f"[YouDo] JSON ошибка {response.url}: {e}")

                page.on("response", on_response)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    logger.warning(f"[YouDo] goto ошибка: {e}")

                # Ждём появления карточек заданий
                try:
                    await page.wait_for_function(
                        "() => [...document.querySelectorAll('a[href]')]"
                        ".some(a => /^\\/t\\d+/.test(a.getAttribute('href')))",
                        timeout=20000,
                    )
                except Exception:
                    logger.warning("[YouDo] Задания не появились за 20 сек.")
                    await page.wait_for_timeout(2000)

                # Небольшая пауза чтобы on_response успел обработать ответ
                await page.wait_for_timeout(2000)

                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[YouDo] Playwright ошибка: {e}")

        if captured_tasks:
            return captured_tasks

        # HTML-fallback: только title+url, без цены/описания
        if html:
            return self._parse_by_links(html)

        return []

    def _raw_candidates(self, data) -> list:
        """Возвращает сырой список задач из JSON без фильтрации."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            ro = data.get("ResultObject") or data.get("resultObject")
            if isinstance(ro, dict):
                items = ro.get("Items") or ro.get("items") or []
                if isinstance(items, list):
                    return items
            for key in ("tasks", "items", "result", "data", "assignments", "orders"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    return val
        return []

    def _extract_from_json(self, data) -> list:
        """Извлекает IT-задания из JSON-ответа YouDo API."""
        candidates = self._raw_candidates(data)

        tasks = []
        for item in candidates[:100]:
            if not isinstance(item, dict):
                continue

            # Фильтр по CategoryFlag — только IT-категории
            flag = (item.get("CategoryFlag") or item.get("categoryFlag") or "").lower()
            if flag and flag not in IT_FLAGS:
                continue

            task = self._item_to_task(item)
            if task:
                tasks.append(task)

        return tasks

    def _item_to_task(self, item: dict):
        task_id = str(
            item.get("Id") or item.get("id") or
            item.get("taskId") or item.get("guid") or ""
        )
        if not task_id:
            return None

        title = (
            item.get("Name") or item.get("name") or
            item.get("title") or item.get("taskTitle") or item.get("subject") or ""
        )
        if isinstance(title, str):
            title = title.strip()
        if not title:
            return None

        href = (
            item.get("Url") or item.get("url") or
            item.get("link") or item.get("taskUrl") or
            f"/t{task_id}"
        )
        if "?" in href:
            href = href.split("?")[0]
        task_url = self.full_url(href)

        description = (
            item.get("Description") or item.get("description") or
            item.get("text") or item.get("body") or ""
        )
        description = (description or "").strip()[:500]

        budget = ""
        for price_key in ("MaxPrice", "PriceAmount", "priceAmount", "MinPrice"):
            val = item.get(price_key)
            if val and isinstance(val, (int, float)) and val > 0:
                prefix = "до " if price_key == "MaxPrice" else ""
                budget = f"{prefix}{int(val)} ₽"
                break

        date = str(
            item.get("CreatedDate") or item.get("createdAt") or
            item.get("date") or item.get("publishedAt") or ""
        )[:10]

        return {
            "id":          task_id,
            "title":       title,
            "description": description,
            "budget":      budget,
            "date":        date,
            "url":         task_url,
        }

    async def enrich_task(self, session, task: dict) -> dict:
        """Подгружает описание и цену из API детали задания."""
        task_id = task.get("id")
        if not task_id:
            return task
        try:
            detail_url = f"https://youdo.com/api/tasks/task/{task_id}/"
            async with session.get(
                detail_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return task
                data = await resp.json(content_type=None)
        except Exception:
            return task

        td = (data.get("ResultObject") or {}).get("TaskData") or {}
        if not td:
            return task

        enriched = dict(task)

        desc = (td.get("Description") or td.get("description") or "").strip()
        if desc:
            enriched["description"] = desc[:500]

        return enriched

    async def _fetch_via_http(self, session, url: str) -> list:
        api_urls = [
            "https://youdo.com/api/tasks/tasks/?count=50&status=opened",
            "https://youdo.com/api/tasks/tasks/?count=50",
        ]
        for api_url in api_urls:
            try:
                async with session.get(
                    api_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        ct = resp.headers.get("content-type", "")
                        if "json" in ct:
                            data = await resp.json(content_type=None)
                            found = self._extract_from_json(data)
                            if found:
                                logger.info(f"[YouDo] HTTP API → {len(found)} задач")
                                return found
            except Exception as e:
                logger.debug(f"[YouDo] HTTP API ошибка {api_url}: {e}")

        html = await self.fetch(session, url)
        if html:
            return self._parse_by_links(html)
        return []

    def _parse_by_links(self, html: str) -> list:
        """HTML-fallback: извлекает ссылки формата /tNNNNNNNN."""
        soup = BeautifulSoup(html, "html.parser")
        tasks = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            clean_href = href.split("?")[0].rstrip("/")
            if not re.match(r'^/t\d{5,}$', clean_href):
                continue
            if clean_href in seen:
                continue
            seen.add(clean_href)
            title = link.get_text(strip=True)
            if len(title) < 5:
                continue
            tasks.append({
                "id":          clean_href[2:],
                "title":       title,
                "description": "",
                "budget":      "",
                "date":        "",
                "url":         self.full_url(clean_href),
            })

        logger.info(f"[YouDo] HTML-fallback: {len(tasks)} заданий.")
        return tasks
