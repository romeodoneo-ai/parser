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


# CategoryFlag значения для категории "Разработка ПО" и всех подкатегорий.
# Если список пустой — берём все категории (фильтр отключён).
IT_CATEGORY_FLAGS = {
    "it",
    "programming",
    "web",
    "mobile",
    "1c",
    "itother",
    "it_other",
    "software",
    "development",
    "webdev",
    "mobiledev",
}


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

                # ── Перехватываем ВСЕ JSON API-ответы ────────────────────────
                async def on_response(response):
                    if response.status != 200:
                        return
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    resp_url = response.url
                    try:
                        data = await response.json()
                        found = self._extract_from_json(data)
                        if found:
                            logger.info(f"[YouDo] API JSON {resp_url} → {len(found)} задач")
                            captured_tasks.extend(found)
                        else:
                            # Временно INFO для отладки — видим что реально приходит
                            preview = str(data)[:200]
                            logger.info(f"[YouDo] JSON (нет задач) {resp_url} :: {preview}")
                    except Exception as e:
                        logger.info(f"[YouDo] JSON ошибка {resp_url}: {e}")

                page.on("response", on_response)

                # ── Загружаем страницу ────────────────────────────────────────
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    logger.warning(f"[YouDo] goto ошибка: {e}")

                # Ждём появления реальных заданий
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('a[href*=\"/tasks/t-\"]').length > 0",
                        timeout=20000,
                    )
                    logger.info("[YouDo] Задания появились на странице.")
                except Exception:
                    logger.warning("[YouDo] Задания не появились за 20 сек.")
                    await page.wait_for_timeout(3000)

                # Прокручиваем для lazy-load
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(1000)

                html = await page.content()

                # ── Дамп всех уникальных href (коротко) ──────────────────────
                soup_debug = BeautifulSoup(html, "html.parser")
                hrefs = sorted({
                    a["href"] for a in soup_debug.find_all("a", href=True)
                    if a["href"].startswith("/") and len(a["href"]) > 5
                })[:40]
                logger.info(f"[YouDo] Все ссылки ({len(hrefs)}): {hrefs}")

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
        candidates = []

        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            # ── Формат YouDo: {ResultObject: {Items: [...]}} ──────────────
            ro = data.get("ResultObject") or data.get("resultObject")
            if isinstance(ro, dict):
                items = ro.get("Items") or ro.get("items") or []
                if isinstance(items, list):
                    candidates = items

            # ── Универсальные ключи (нижний регистр) ──────────────────────
            if not candidates:
                for key in ("tasks", "items", "result", "data", "assignments", "orders"):
                    val = data.get(key)
                    if isinstance(val, list) and val:
                        candidates = val
                        break
                    if isinstance(val, dict):
                        for subkey in ("tasks", "items", "result", "assignments",
                                       "Items", "Tasks"):
                            sub = val.get(subkey)
                            if isinstance(sub, list) and sub:
                                candidates = sub
                                break

        # Логируем все уникальные CategoryFlag — чтобы знать точные значения
        all_flags = {
            str(item.get("CategoryFlag") or item.get("categoryFlag") or "")
            for item in candidates if isinstance(item, dict)
        }
        if all_flags:
            logger.info(f"[YouDo] CategoryFlag в ответе: {sorted(all_flags)}")

        skipped_flags = set()
        for item in candidates[:100]:
            if not isinstance(item, dict):
                continue
            # Фильтр по категории "Разработка ПО"
            flag = str(item.get("CategoryFlag") or item.get("categoryFlag") or "").lower()
            if IT_CATEGORY_FLAGS and flag and flag not in IT_CATEGORY_FLAGS:
                skipped_flags.add(flag)
                continue
            task = self._item_to_task(item)
            if task:
                tasks.append(task)

        if skipped_flags:
            logger.info(f"[YouDo] Отфильтровано по категории (не IT): {sorted(skipped_flags)}")
        logger.info(f"[YouDo] _extract_from_json: кандидатов={len(candidates)}, прошло={len(tasks)}")
        return tasks

    def _item_to_task(self, item: dict):
        """Конвертирует один JSON-объект задания в стандартный формат."""
        # ID — YouDo использует 'Id' (с заглавной), стандарт — 'id'
        task_id = str(
            item.get("Id") or item.get("id") or
            item.get("taskId") or item.get("guid") or ""
        )
        if not task_id:
            return None

        # Заголовок — YouDo использует 'Name'
        title = (
            item.get("Name") or item.get("name") or
            item.get("title") or item.get("taskTitle") or item.get("subject") or ""
        )
        if isinstance(title, str):
            title = title.strip()
        if not title:
            return None

        # URL — реальный формат YouDo: https://youdo.com/t{Id}
        href = (
            item.get("Url") or item.get("url") or
            item.get("link") or item.get("taskUrl") or
            f"/t{task_id}"
        )
        # Убираем searchRequestId из URL если он есть
        if "?" in href:
            href = href.split("?")[0]
        task_url = self.full_url(href)

        # Описание
        description = (
            item.get("Description") or item.get("description") or
            item.get("text") or item.get("body") or ""
        )
        description = (description or "").strip()[:500]

        # Бюджет — YouDo использует 'PriceAmount'
        price_amount = item.get("PriceAmount") or item.get("priceAmount")
        if price_amount is not None and price_amount != 0:
            budget = f"{price_amount} ₽"
        else:
            price = item.get("price") or item.get("budget") or item.get("reward") or {}
            if isinstance(price, dict):
                val = price.get("amount") or price.get("value") or ""
                cur = price.get("currency", "₽")
                budget = f"{val} {cur}".strip() if val else ""
            else:
                budget = str(price) if price else ""

        # Категория (дополнительно для контекста)
        category = item.get("CategoryFlag") or item.get("categoryFlag") or ""

        # Дата
        date = str(
            item.get("CreatedDate") or item.get("createdAt") or
            item.get("date") or item.get("publishedAt") or ""
        )[:10]

        return {
            "id":          task_id,
            "title":       title,
            "description": (f"[{category}] " if category else "") + description,
            "budget":      budget,
            "date":        date,
            "url":         task_url,
        }

    # ─────────────────────────────────────────────────────────────────────────
    def _parse_html(self, html: str) -> list:
        """Парсит HTML (после JS-рендера)."""
        soup = BeautifulSoup(html, "html.parser")

        # Сначала ищем ссылки на задания — самый надёжный способ
        tasks = self._parse_by_links(soup)
        if tasks:
            return tasks

        # Резервно — ищем карточки по data-атрибутам
        cards = (
            soup.select("[data-testid*='task']") or
            soup.select("[data-task-id]") or
            []
        )
        if cards:
            logger.info(f"[YouDo] HTML: {len(cards)} карточек по data-атрибутам.")
            for card in cards:
                try:
                    link = card.select_one("a[href]")
                    if not link:
                        continue
                    href  = link.get("href", "")
                    title = link.get_text(strip=True) or card.get_text(" ", strip=True)[:100]
                    if len(title) < 5:
                        continue
                    tasks.append({
                        "id": href.rstrip("/").split("/")[-1],
                        "title": title, "description": "",
                        "budget": "", "date": "",
                        "url": self.full_url(href),
                    })
                except Exception:
                    pass

        if not tasks:
            text_sample = soup.get_text(" ", strip=True)[:300]
            logger.warning(f"[YouDo] HTML: 0 задач. Текст: {text_sample!r}")

        return tasks

    # ─────────────────────────────────────────────────────────────────────────
    async def _fetch_via_http(self, session, url: str) -> list:
        """
        Прямой HTTP-запрос — работает если YouDo отдаёт SSR.
        Также пробует прямой API-эндпоинт.
        """
        tasks = []

        # Прямой API YouDo (эндпоинт подтверждён из логов)
        # Пробуем сначала с фильтром по категории IT, затем без фильтра (фильтруем сами)
        api_urls = [
            "https://youdo.com/api/tasks/tasks/?count=50&categories[]=it&status=opened",
            "https://youdo.com/api/tasks/tasks/?count=50&page=0&status=opened",
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
        """Ищет только реальные ссылки на задания формата /tNNNNNNNN."""
        tasks = []
        seen  = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            clean_href = href.split("?")[0].rstrip("/")
            # Реальный формат YouDo: /t14682758 (буква t + только цифры)
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

        logger.info(f"[YouDo] _parse_by_links: {len(tasks)} ссылок на задания.")
        return tasks
