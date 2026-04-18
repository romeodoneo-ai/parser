"""
Парсер Freelance.ru
https://freelance.ru/project/search?...
"""

import re
from bs4 import BeautifulSoup
from .base import BaseParser, logger


class FreelanceRuParser(BaseParser):
    name = "Freelance.ru"
    base_url = "https://freelance.ru"

    async def get_tasks(self, session, url: str) -> list:
        html = await self.fetch(session, url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        tasks = []

        # Карточки проектов
        cards = (
            soup.select("div.project-card") or
            soup.select("div[class*='project-card']") or
            soup.select("div[class*='project_card']") or
            soup.select("ul.projects-list li") or
            []
        )

        # Запасной вариант — ищем ссылки на проекты
        if not cards:
            return self._parse_by_links(soup)

        for card in cards:
            try:
                title_tag = (
                    card.select_one("h3 a") or
                    card.select_one("h2 a") or
                    card.select_one("a[href*='/project/']")
                )
                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                href     = title_tag.get("href", "")
                task_url = self.full_url(href)

                m = re.search(r"/project/([^/]+)", href)
                task_id = m.group(1) if m else href

                desc_tag  = card.select_one("p, .description, [class*='desc']")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                budget_tag = card.select_one("[class*='budget'], [class*='price'], .budget")
                budget = budget_tag.get_text(strip=True) if budget_tag else ""

                date_tag = card.select_one("time, [class*='date'], [class*='time']")
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

    def _parse_by_links(self, soup) -> list:
        """Запасной парсинг — ищем все ссылки на проекты."""
        tasks = []
        seen  = set()

        for link in soup.select("a[href*='/project/']"):
            href = link.get("href", "")
            m    = re.search(r"/project/([^/?]+)", href)
            if not m:
                continue
            task_id = m.group(1)
            if task_id in seen:
                continue
            seen.add(task_id)

            title = link.get_text(strip=True)
            if not title:
                continue

            tasks.append({
                "id":          task_id,
                "title":       title,
                "description": "",
                "budget":      "",
                "date":        "",
                "url":         self.full_url(href),
            })

        return tasks
