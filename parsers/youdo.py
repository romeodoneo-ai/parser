"""
Парсер YouDo.com.

Стратегия (по приоритету):
  1. Перехват XHR/fetch ответов — ловим JSON с заданиями прямо из сети.
  2. Парсинг HTML через Playwright — если в JSON ничего не нашли.
  3. Запасной HTTP-запрос без JS — на случай если Playwright недоступен.

https://youdo.com/tasks-all-opened-all
"""

import json
import re
import asyncio
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
        # ── Стратегия 1: Playwright + перехват сетевых запросов ──────────────
        if PLAYWRIGHT_OK:
            tasks = await self._fetch_via_playwright(url)
            if tasks:
                logger.info(f"[YouDo] Найдено через Playwright/API: {len(tasks)}")
                return tasks
            logger.warning("[YouDo] Playwright вернул 0 задач — пробуем HTTP-запрос.")

        # ── Стратегия 2: обычный HTTP (работает если YouDo отдаёт SSR) ────────
        tasks = await self._fetch_via_http(session, url)
        logger.info(f"[YouDo] Найдено через HTTP: {len(tasks)}")
        return tasks

    # ─────────────────────────────────────────────────────────────────────────
    async def _fetch_via_playwright(self, url: str) -> list:
        """Запускает браузер, ловит JSON из API-запросов, парсит HTML как fallback."""
        captured_tasks = []

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

                # ── Перехватываем API-ответы ──────────────────────────────────
                async def on_response(response):
                    resp_url = response.url
                    # YouDo использует /api/tasks/ и /graphql
                    if not any(k in resp_url for k in ("/api/task", "/tasks", "graphql")):
                        return
                    if response.status != 200:
                        return
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    try:
                        data = await response.json()
                        found = self._extract_from_json(data)
                        if found:
                            logger.info(f"[YouDo] API-ответ с {resp_url} → {len(found)} задач")
                            captured_tasks.extend(found)
                    except Exception as e:
                        logger.debug(f"[YouDo] Не удалось разобрать JSON с {resp_url}: {e}")

                page.on("response", on_response)

                # ── Загружаем страницу ─────────────────────────────────────────
                try:
                    await page.goto(url, wait_until="networkidle", timeout=45000)
                except Exception:
                    # networkidle может таймаутить на динамичных сайтах — продолжаем
                    pass

                await page.wait_for_timeout(5000)

                # Прокручиваем для lazy-load
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await page.wait_for_timeout(1500)

                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[YouDo] Playwright ошибка: {e}")
            return captured_tasks

        # Если API не дал результатов — парсим HTML
        if not captured_tasks:
            captured_tasks = self._parse_html(html)

        return captured_tasks

    # ─────────────────────────────────────────────────────────────────────────
    def _extract_from_json(self, data) -> list:
        """Пробует достать задания из разных форматов JSON-ответа YouDo."""
        tasks = []

        # Вариант 1: {tasks: [...]} или {items: [...]} или {result: [...]}
        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            for key in ("tasks", "items", "result", "data", "assignments", "orders"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    candidates = val
                    break
                if isinstance(val, dict):
                    # {data: {tasks: [...]}}
                    for subkey in ("tasks", "items", "result", "assignments"):
                        sub = val.get(subkey)
                        if isinstance(sub, list) and sub:
                            candidates = sub
                            break

        for item in candidates[:50]:
            if not isinstance(item, dict):
                continue
            task = self._item_to_task(item)
            if task:
                tasks.append(task)

        return tasks

    def _item_to_task(self, item: dict) -> dict | None:
        """Конвертирует один JSON-объект задания в стандартный формат."""
        # ID
        task_id = str(item.get("id") or item.get("taskId") or item.get("guid") or "")
        if not task_id:
            return None

        # Заголовок
        title = (
            item.get("title") or item.get("name") or
            item.get("taskTitle") or item.get("subject") or ""
        ).strip()
        if not title:
            return None

        # URL
        href = (
            item.get("url") or item.get("link") or
            item.get("taskUrl") or f"/tasks/t-{task_id}/"
        )
        task_url = self.full_url(href)

        # Описание
        description = (
            item.get("description") or item.get("text") or
            item.get("taskDescription") or item.get("body") or ""
        ).strip()

        # Бюджет
        price = item.get("price") or item.get("budget") or item.get("reward") or {}
        if isinstance(price, dict):
            budget = str(price.get("amount") or price.get("value") or "")
            currency = price.get("currency", "")
            budget = f"{budget} {currency}".strip() if budget else ""
        else:
            budget = str(price) if price else ""

        # Дата
        date = str(
            item.get("createdAt") or item.get("date") or
            item.get("publishedAt") or item.get("created") or ""
        )[:10]

        return {
            "id":          task_id,
            "title":       title,
            "description": description[:500],
            "budget":      budget,
            "date":        date,
            "url":         task_url,
        }

    # ─────────────────────────────────────────────────────────────────────────
    def _parse_html(self, html: str) -> list:
        """Парсит HTML (после JS-рендера) с расширенным набором селекторов."""
        soup = BeautifulSoup(html, "html.parser")
        tasks = []

        # YouDo генерирует минифицированные классы — ищем по data-атрибутам и структуре
        cards = (
            soup.select("[data-testid*='task']") or
            soup.select("[data-task-id]") or
            soup.select("[data-id]") or
            soup.select("li[class*='Task']") or
            soup.select("li[class*='task']") or
            soup.select("div[class*='Task']") or
            soup.select("div[class*='task']") or
            soup.select("article") or
            []
        )

        if cards:
            logger.info(f"[YouDo] HTML: найдено {len(cards)} карточек через CSS-селекторы.")
            for card in cards:
                try:
                    link = (
                        card.select_one("a[href*='/tasks/']") or
                        card.select_one("a[href*='/task/']")
                    )
                    if not link:
                        continue
                    href  = link.get("href", "")
                    title = link.get_text(strip=True) or card.get_text(" ", strip=True)[:100]
                    if len(title) < 5:
                        continue
                    task_id = href.rstrip("/").split("/")[-1]
                    tasks.append({
                        "id": task_id, "title": title, "description": "",
                        "budget": "", "date": "",
                        "url": self.full_url(href),
                    })
                except Exception:
                    pass
        else:
            tasks = self._parse_by_links(soup)

        # Логируем для отладки
        if not tasks:
            text_sample = soup.get_text(" ", strip=True)[:300]
            logger.warning(f"[YouDo] HTML парсинг: 0 задач. Текст страницы: {text_sample!r}")

        return tasks

    # ─────────────────────────────────────────────────────────────────────────
    async def _fetch_via_http(self, session, url: str) -> list:
        """
        Прямой HTTP-запрос — работает если YouDo отдаёт SSR.
        Также пробует прямой API-эндпоинт.
        """
        tasks = []

        # Пробуем прямой API (известные эндпоинты YouDo)
        api_urls = [
            "https://youdo.com/api/tasks/?count=30&page=0&status=opened",
            "https://youdo.com/api/assignments/?count=30&status=opened",
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
                                logger.info(f"[YouDo] HTTP API {api_url} → {len(found)} задач")
                                return found
            except Exception as e:
                logger.debug(f"[YouDo] HTTP API ошибка {api_url}: {e}")

        # Обычная HTML-страница
        html = await self.fetch(session, url)
        if html:
            tasks = self._parse_html(html)

        return tasks

    def _parse_by_links(self, soup) -> list:
        tasks = []
        seen  = set()
        for link in soup.select("a[href*='/tasks/'], a[href*='/task/']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            # Исключаем служебные страницы
            if href in ("/tasks-all-opened-all", "/tasks/") or "?" in href.split("/")[-1]:
                continue
            seen.add(href)
            title = link.get_text(strip=True)
            if len(title) < 5:
                continue
            tasks.append({
                "id":          href.rstrip("/").split("/")[-1],
                "title":       title,
                "description": "",
                "budget":      "",
                "date":        "",
                "url":         self.full_url(href),
            })
        logger.info(f"[YouDo] _parse_by_links: {len(tasks)} ссылок на задания.")
        return tasks
