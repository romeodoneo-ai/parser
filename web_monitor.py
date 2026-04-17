"""
Мониторинг сайтов.
Периодически проверяет страницы на наличие новых заказов по ключевым словам.
"""

import asyncio
import hashlib
import logging
import re

import aiohttp
from bs4 import BeautifulSoup

import storage
import filters
from notifier import format_notification

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def extract_text(html: str) -> str:
    """Вытаскивает чистый текст из HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # Убираем скрипты, стили, навигацию
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Убираем пустые строки
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def check_site(session: aiohttp.ClientSession, site: dict, bot_client, user_id: int):
    """Проверяет один сайт."""
    url = site["url"]
    name = site["name"]

    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                logger.warning(f"[{name}] HTTP {resp.status}")
                return
            html = await resp.text()

        text = extract_text(html)
        new_hash = content_hash(text)
        old_hash = storage.get_web_hash(url)

        # Первый раз — просто запоминаем, не уведомляем
        if old_hash is None:
            storage.set_web_hash(url, new_hash)
            logger.info(f"[{name}] Первая проверка — запомнили содержимое.")
            return

        # Контент не изменился
        if old_hash == new_hash:
            logger.info(f"[{name}] Изменений нет.")
            return

        # Контент изменился — ищем ключевые слова
        storage.set_web_hash(url, new_hash)
        matched, keywords = filters.is_match(text)

        if not matched:
            logger.info(f"[{name}] Страница обновилась, но ключевых слов нет.")
            return

        logger.info(f"[{name}] Найдено обновление! Слова: {keywords}")

        # Формируем уведомление
        # Берём фрагменты текста где встречаются ключевые слова
        snippet = _find_snippet(text, keywords)
        notification = format_notification(
            f"🌐 {name}",
            snippet,
            keywords,
            url,
        )

        await bot_client.send_message(user_id, notification, parse_mode="md", link_preview=False)
        storage.save_match(url, None, snippet, keywords)

    except asyncio.TimeoutError:
        logger.warning(f"[{name}] Таймаут при запросе.")
    except Exception as e:
        logger.error(f"[{name}] Ошибка: {e}")


def _find_snippet(text: str, keywords: list, context_lines: int = 5) -> str:
    """Находит фрагмент текста вокруг найденных ключевых слов."""
    lines = text.splitlines()
    result_lines = []
    found_indices = set()

    for i, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in keywords):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            for j in range(start, end):
                found_indices.add(j)

    for i in sorted(found_indices):
        result_lines.append(lines[i])

    snippet = "\n".join(result_lines[:50])  # Не больше 50 строк
    return snippet if snippet else text[:500]


class WebMonitor:
    def __init__(self, config: dict, bot_client, paused_ref):
        self.config = config
        self.bot_client = bot_client
        self.paused_ref = paused_ref  # ссылка на monitor.paused
        self.user_id = config["telegram"]["your_user_id"]

        # Загружаем сайты из config.yaml в БД
        for site in config.get("websites", []):
            storage.add_website(site["url"], site["name"], site.get("interval_minutes", 20))

    async def run(self):
        """Основной цикл проверки сайтов."""
        logger.info("Веб-мониторинг запущен.")
        # Словарь: url -> время последней проверки
        last_checked = {}

        async with aiohttp.ClientSession() as session:
            while True:
                await asyncio.sleep(60)  # Просыпаемся каждую минуту

                if self.paused_ref():
                    continue

                sites = storage.get_websites()
                now = asyncio.get_event_loop().time()

                for site in sites:
                    url = site["url"]
                    interval_sec = site["interval_minutes"] * 60
                    last = last_checked.get(url, 0)

                    if now - last >= interval_sec:
                        last_checked[url] = now
                        await check_site(session, site, self.bot_client, self.user_id)
