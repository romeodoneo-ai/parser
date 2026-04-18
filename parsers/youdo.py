"""
Парсер YouDo.com через Playwright (сайт требует JavaScript).
https://youdo.com/tasks-all-opened-all

Фильтр "Разработка ПО" применяется через клик на странице.
"""

from bs4 import BeautifulSoup
from .base import BaseParser, logger

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# Категория "Разработка ПО" на YouDo
CATEGORY_SELECTOR = "text=Разработка ПО"


class YoudoParser(BaseParser):
    name = "YouDo"
    base_url = "https://youdo.com"

    async def get_tasks(self, session, url: str) -> list:
        if not PLAYWRIGHT_OK:
            logger.warning("[YouDo] Playwright не установлен. Пропускаем.")
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
                await page.wait_for_timeout(4000)  # ждём загрузки заданий

                # Пробуем кликнуть на фильтр "Разработка ПО"
                try:
                    filter_btn = page.locator(CATEGORY_SELECTOR).first
                    if await filter_btn.is_visible(timeout=3000):
                        await filter_btn.click()
                        await page.wait_for_timeout(3000)
                        logger.info("[YouDo] Фильтр 'Разработка ПО' применён.")
                except Exception:
                    logger.info("[YouDo] Фильтр не найден — парсим все задания.")

                html = await page.content()
                await browser.close()

        except Exception as e:
            logger.error(f"[YouDo] Playwright ошибка: {e}")
            return []

        soup  = BeautifulSoup(html, "html.parser")
        tasks = []

        # YouDo: карточки заданий
        cards = (
            soup.select("li[class*='task']") or
            soup.select("div[class*='task-item']") or
            soup.select("div[class*='TaskItem']") or
            soup.select("article[class*='task']") or
            soup.select("div[class*='assignment']") or
            []
        )

        if not cards:
            return self._parse_by_links(soup)

        for card in cards:
            try:
                title_tag = (
                    card.select_one("a[class*='title']") or
                    card.select_one("h3 a") or
                    card.select_one("h2 a") or
                    card.select_one("a[href*='/tasks/']")
                )
                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                href     = title_tag.get("href", "")
                task_url = self.full_url(href)
                task_id  = href.rstrip("/").split("/")[-1]

                desc_tag = (
                    card.select_one("[class*='description']") or
                    card.select_one("[class*='desc']") or
                    card.select_one("p")
                )
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                price_tag = (
                    card.select_one("[class*='price']") or
                    card.select_one("[class*='budget']") or
                    card.select_one("[class*='reward']") or
                    card.select_one("[class*='cost']")
                )
                budget = price_tag.get_text(strip=True) if price_tag else ""

                date_tag = (
                    card.select_one("time") or
                    card.select_one("[class*='date']") or
                    card.select_one("[class*='time']")
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
                logger.debug(f"[YouDo] Пропускаем карточку: {e}")

        logger.info(f"[YouDo] Найдено карточек: {len(tasks)}")
        return tasks

    def _parse_by_links(self, soup) -> list:
        tasks = []
        seen  = set()
        for link in soup.select("a[href*='/tasks/']"):
            href = link.get("href", "")
            if not href or href in seen or href == "/tasks-all-opened-all":
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
