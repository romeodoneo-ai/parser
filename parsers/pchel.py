"""
Парсер Pchel.net
https://pchel.net/jobs/website-development/
"""

from bs4 import BeautifulSoup
from .base import BaseParser, logger


class PchelParser(BaseParser):
    name = "Пчел.net"
    base_url = "https://pchel.net"

    async def get_tasks(self, session, url: str) -> list:
        html = await self.fetch(session, url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        tasks = []

        cards = soup.select("div.project-card") or soup.select("div[class*='project']")

        for card in cards:
            try:
                # Заголовок и ссылка
                title_tag = (
                    card.select_one(".project-header a") or
                    card.select_one("h2 a") or
                    card.select_one("h3 a") or
                    card.select_one("a[href*='/jobs/']")
                )
                if not title_tag:
                    continue

                title    = title_tag.get_text(strip=True)
                href     = title_tag.get("href", "")
                task_url = self.full_url(href)
                task_id  = href.rstrip("/").split("/")[-1]

                # Описание
                desc_tag = (
                    card.select_one(".project-description") or
                    card.select_one("p")
                )
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                # Бюджет
                budget_tag = (
                    card.select_one(".budget") or
                    card.select_one("[class*='budget']") or
                    card.select_one("[class*='price']")
                )
                budget = budget_tag.get_text(strip=True) if budget_tag else ""

                # Работодатель
                employer_tag = card.select_one(".employer")
                employer = employer_tag.get_text(strip=True) if employer_tag else ""

                tasks.append({
                    "id":          task_id,
                    "title":       title,
                    "description": description + (f"\n👤 {employer}" if employer else ""),
                    "budget":      budget,
                    "date":        "",
                    "url":         task_url,
                })

            except Exception as e:
                logger.debug(f"[{self.name}] Пропускаем карточку: {e}")

        logger.info(f"[{self.name}] Найдено карточек: {len(tasks)}")
        return tasks
