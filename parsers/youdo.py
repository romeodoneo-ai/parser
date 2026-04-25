"""
Парсер YouDo.com.

Стратегия (по приоритету):
  1. Перехват XHR/fetch ответов через Playwright — JSON с полными данными задания.
  2. HTML-парсинг через Playwright — если JSON не поймали (только title+url).
  3. Прямой HTTP к API — если Playwright недоступен.

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

                # Перехватываем JSON-ответы YouDo API
                async def on_response(response):
                    if response.status != 200:
                        return
                    if "youdo.com/api/tasks" not in response.url:
                        return
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    try:
                        data = await response.json()
                        found = self._extract_from_json(data)
                        if found:
                            logger.info(f"[YouDo] API {response.url} → {len(found)} задач")
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

                # Прокрутка для подгрузки lazy-load
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(700)

                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[YouDo] Playwright ошибка: {e}")

        # JSON-перехват дал полные данные — возвращаем
        if captured_tasks:
            return captured_tasks

        # HTML-fallback: только title+url, без цены/описания
        if html:
            return self._parse_by_links(html)

        return []

    def _extract_from_json(self, data) -> list:
        """Извлекает задания из JSON-ответа YouDo API."""
        candidates = []

        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            ro = data.get("ResultObject") or data.get("resultObject")
            if isinstance(ro, dict):
                items = ro.get("Items") or ro.get("items") or []
                if isinstance(items, list):
                    candidates = items

            if not candidates:
                for key in ("tasks", "items", "result", "data", "assignments", "orders"):
                    val = data.get(key)
                    if isinstance(val, list) and val:
                        candidates = val
                        break
                    if isinstance(val, dict):
                        for subkey in ("tasks", "items", "result", "assignments", "Items", "Tasks"):
                            sub = val.get(subkey)
                            if isinstance(sub, list) and sub:
                                candidates = sub
                                break

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

        # Ищем цену во всех известных полях YouDo API
        budget = ""
        for price_key in ("PriceAmount", "priceAmount", "Price", "price",
                          "MinPrice", "minPrice", "MaxPrice", "maxPrice",
                          "budget", "reward", "amount"):
            val = item.get(price_key)
            if val is None:
                continue
            if isinstance(val, (int, float)) and val > 0:
                budget = f"{int(val)} ₽"
                break
            if isinstance(val, dict):
                amt = val.get("amount") or val.get("value") or 0
                if amt and int(amt) > 0:
                    cur = val.get("currency", "₽")
                    budget = f"{int(amt)} {cur}"
                    break
        if not budget:
            budget = "Договорная"

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
