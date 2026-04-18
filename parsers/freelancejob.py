"""
Парсер Freelancejob.ru
https://www.freelancejob.ru/projects/
"""

import re
from bs4 import BeautifulSoup
from .base import BaseParser, logger


class FreelancejobParser(BaseParser):
    name = "Freelancejob.ru"
    base_url = "https://www.freelancejob.ru"

    async def get_tasks(self, session, url: str) -> list:
        html = await self.fetch(session, url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        tasks = []

        # Ищем все ссылки вида /vacancy/ID/
        links = soup.select("a[href*='/vacancy/']")
        seen_ids = set()

        for link in links:
            try:
                href = link.get("href", "")
                m = re.search(r"/vacancy/(\d+)/", href)
                if not m:
                    continue

                task_id = m.group(1)
                if task_id in seen_ids:
                    continue
                seen_ids.add(task_id)

                title    = link.get_text(strip=True)
                if not title:
                    continue

                task_url = self.full_url(href)

                # Пробуем найти родительский блок с описанием и бюджетом
                parent = link.find_parent("div") or link.find_parent("li") or link.find_parent("tr")

                description = ""
                budget      = ""
                date        = ""

                if parent:
                    text = parent.get_text(" ", strip=True)

                    # Бюджет: "Бюджет: X руб."
                    bm = re.search(r"[Бб]юджет[:\s]+([\d\s]+руб[^\n,]*|по договор[^\n,]*)", text)
                    budget = bm.group(1).strip() if bm else ""

                    # Дата: "Проект добавлен: ДД.ММ.ГГГГ"
                    dm = re.search(r"добавлен[:\s]+(\d{2}\.\d{2}\.\d{4}[^\n]*)", text)
                    date = dm.group(1).strip() if dm else ""

                    # Описание — всё остальное
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    desc_lines = [
                        l for l in lines
                        if l != title
                        and "Бюджет" not in l
                        and "добавлен" not in l
                        and "Удалённая" not in l
                    ]
                    description = " ".join(desc_lines[:3])

                tasks.append({
                    "id":          task_id,
                    "title":       title,
                    "description": description,
                    "budget":      budget,
                    "date":        date,
                    "url":         task_url,
                })

            except Exception as e:
                logger.debug(f"[{self.name}] Пропускаем: {e}")

        logger.info(f"[{self.name}] Найдено карточек: {len(tasks)}")
        return tasks
