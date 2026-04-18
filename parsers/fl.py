"""
Парсер FL.ru
Работает для всех категорий:
  https://www.fl.ru/projects/category/saity/
  https://www.fl.ru/projects/category/programmirovanie/
  https://www.fl.ru/projects/category/dizajn/
  и т.д.
"""

import re
from bs4 import BeautifulSoup
from .base import BaseParser, logger


class FlParser(BaseParser):
    name = "FL.ru"
    base_url = "https://www.fl.ru"

    async def get_tasks(self, session, url: str) -> list:
        html = await self.fetch(session, url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        tasks = []

        # FL.ru: проекты лежат в div.b-post
        cards = soup.select("div.b-post")

        if not cards:
            # Запасной вариант
            cards = soup.select("div[class*='project']") or soup.select("article")

        for card in cards:
            try:
                # Ссылка и заголовок
                title_tag = (
                    card.select_one("h2 a") or
                    card.select_one("h3 a") or
                    card.select_one(".b-post__title a") or
                    card.select_one("a[href*='/projects/']")
                )
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                href  = title_tag.get("href", "")
                if not href or "/projects/" not in href:
                    continue

                task_url = self.full_url(href)

                # ID проекта из URL
                m = re.search(r"/projects/(\d+)/", href)
                task_id = m.group(1) if m else href

                # Описание
                desc_tag = (
                    card.select_one(".b-post__body") or
                    card.select_one(".b-post__txt") or
                    card.select_one("p")
                )
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                # Бюджет
                budget_tag = (
                    card.select_one(".b-post__price") or
                    card.select_one("[class*='price']") or
                    card.select_one("[class*='budget']")
                )
                budget = budget_tag.get_text(strip=True) if budget_tag else ""

                # Дата
                date_tag = (
                    card.select_one("[class*='date']") or
                    card.select_one("[class*='time']") or
                    card.select_one("time")
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
                logger.debug(f"[{self.name}] Пропускаем карточку: {e}")

        logger.info(f"[{self.name}] Найдено карточек: {len(tasks)}")
        return tasks
