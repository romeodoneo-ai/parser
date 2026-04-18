"""
Парсер Weblancer.net через Playwright (сайт блокирует обычные запросы).
https://www.weblancer.net/freelance/
"""

import re
from bs4 import BeautifulSoup
from .base import BaseParser, logger

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False


class WeblancerParser(BaseParser):
    name = "Weblancer"
    base_url = "https://www.weblancer.net"

    async def get_tasks(self, session, url: str) -> list:
        if not PLAYWRIGHT_OK:
            logger.warning("[Weblancer] Playwright не установлен. Пропускаем.")
            return []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="ru-RU",
                )
                page = await context.new_page()

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)  # ждём подгрузки JS

                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[Weblancer] Playwright ошибка: {e}")
            return []

        soup  = BeautifulSoup(html, "html.parser")
        tasks = []

        # Weblancer: карточки проектов
        cards = (
            soup.select("div.cols-table_item") or
            soup.select("div.item[class*='project']") or
            soup.select("div[class*='vacancy']") or
            soup.select("div.b-vacancy-list__item") or
            []
        )

        # Запасной вариант — ищем ссылки на проекты
        if not cards:
            return self._parse_by_links(soup)

        for card in cards:
            try:
                title_tag = (
                    card.select_one(".title a") or
                    card.select_one("h2 a") or
                    card.select_one("h3 a") or
                    card.select_one("a[href*='/jobs/']") or
                    card.select_one("a[href*='/projects/']")
                )
                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                href     = title_tag.get("href", "")
                task_url = self.full_url(href)
                task_id  = href.rstrip("/").split("/")[-1]

                desc_tag = (
                    card.select_one(".description") or
                    card.select_one("p") or
                    card.select_one("[class*='desc']")
                )
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                budget_tag = (
                    card.select_one(".cost") or
                    card.select_one("[class*='price']") or
                    card.select_one("[class*='budget']") or
                    card.select_one("[class*='cost']")
                )
                budget = budget_tag.get_text(strip=True) if budget_tag else ""

                date_tag = (
                    card.select_one(".date") or
                    card.select_one("time") or
                    card.select_one("[class*='date']")
                )
                date = date_tag.get_text(strip=True) if date_tag else ""

                tasks.append({
                    "id":          task_id,
                    "title":       title,
                    "description": description,
                    "budget":      budget,
                    "date":        date,
                    "url":         task_url,
                })

            except Exception as e:
                logger.debug(f"[Weblancer] Пропускаем карточку: {e}")

        logger.info(f"[Weblancer] Найдено карточек: {len(tasks)}")
        return tasks

    def _parse_by_links(self, soup) -> list:
        tasks = []
        seen  = set()
        for link in soup.select("a[href*='/jobs/'], a[href*='/projects/']"):
            href = link.get("href", "")
            if not href or href in seen:
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
        return tasks
