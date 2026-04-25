"""
Парсер YouDo.com.

API принимает POST на /api/tasks/tasks/ с JSON-телом.
Фильтрация по категории — параметр "sub" (массив ID подкатегорий).
ID для IT/разработки получены из реального браузерного запроса.
"""

import re
import json
import uuid
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from .base import BaseParser, HEADERS, logger

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# ID подкатегорий IT/разработки на YouDo (из браузерного Network-запроса)
IT_SUB_IDS = [148, 146, 62, 63, 244, 245, 147, 246, 108]

API_URL = "https://youdo.com/api/tasks/tasks/"

API_HEADERS = {
    **HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://youdo.com/tasks-all-opened-all",
    "Origin": "https://youdo.com",
}


def _build_payload(page: int = 1) -> dict:
    return {
        "q": "",
        "list": "all",
        "status": "opened",
        "radius": 50,
        "page": page,
        "noOffers": False,
        "onlySbr": False,
        "onlyB2B": False,
        "onlyVacancies": False,
        "priceMin": "",
        "sortType": 1,
        "onlyVirtual": False,
        "sub": IT_SUB_IDS,
        "searchRequestId": str(uuid.uuid4()),
    }


class YoudoParser(BaseParser):
    name = "YouDo"
    base_url = "https://youdo.com"

    async def get_tasks(self, session, url: str) -> list:
        tasks = await self._fetch_via_post(session)
        if tasks:
            logger.info(f"[YouDo] Найдено через POST API: {len(tasks)}")
            return tasks

        logger.warning("[YouDo] POST API вернул 0 — пробуем Playwright.")
        if PLAYWRIGHT_OK:
            tasks = await self._fetch_via_playwright(url)
            if tasks:
                logger.info(f"[YouDo] Найдено через Playwright: {len(tasks)}")
                return tasks

        return []

    async def _fetch_via_post(self, session) -> list:
        all_tasks = []
        page = 1
        while True:
            payload = _build_payload(page)
            try:
                async with session.post(
                    API_URL,
                    headers=API_HEADERS,
                    data=json.dumps(payload),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"[YouDo] POST API вернул {resp.status}")
                        break
                    ct = resp.headers.get("content-type", "")
                    if "json" not in ct:
                        break
                    data = await resp.json(content_type=None)
            except Exception as e:
                logger.error(f"[YouDo] POST API ошибка (стр. {page}): {e}")
                break

            tasks = self._extract_from_json(data)
            if not tasks:
                break
            all_tasks.extend(tasks)

            ro = (data.get("ResultObject") or {})
            total = ro.get("Total") or 0
            items_on_page = ro.get("ItemsOnPage") or 50
            if len(all_tasks) >= total or len(tasks) < items_on_page:
                break
            page += 1
            await asyncio.sleep(0.5)

        logger.info(f"[YouDo] POST API → {len(all_tasks)} IT-заданий ({page} стр.)")
        return all_tasks

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
                        found = self._extract_from_json(data)
                        if found:
                            captured_tasks.extend(found)
                    except Exception as e:
                        logger.debug(f"[YouDo] JSON ошибка {response.url}: {e}")

                page.on("response", on_response)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    logger.warning(f"[YouDo] goto ошибка: {e}")

                try:
                    await page.wait_for_function(
                        "() => [...document.querySelectorAll('a[href]')]"
                        ".some(a => /^\\/t\\d+/.test(a.getAttribute('href')))",
                        timeout=20000,
                    )
                except Exception:
                    logger.warning("[YouDo] Задания не появились за 20 сек.")
                    await page.wait_for_timeout(2000)

                await page.wait_for_timeout(2000)
                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[YouDo] Playwright ошибка: {e}")

        if captured_tasks:
            return captured_tasks
        if html:
            return self._parse_by_links(html)
        return []

    def _raw_candidates(self, data) -> list:
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
        candidates = self._raw_candidates(data)
        tasks = []
        for item in candidates[:100]:
            if not isinstance(item, dict):
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
            "id":           task_id,
            "title":        title,
            "description":  description,
            "budget":       budget,
            "date":         date,
            "url":          task_url,
            "offers_count": int(item.get("OffersCount") or 0),
            "is_sbr":       bool(item.get("IsSbr")),
        }

    async def enrich_task(self, session, task: dict) -> dict:
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

    def _parse_by_links(self, html: str) -> list:
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
