"""
Базовый класс для всех парсеров сайтов.
"""

import logging
import aiohttp

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


class BaseParser:
    name = "Unknown"
    base_url = ""

    async def fetch(self, session: aiohttp.ClientSession, url: str):
        """Скачивает страницу и возвращает HTML или None."""
        try:
            async with session.get(
                url,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                logger.warning(f"[{self.name}] HTTP {resp.status} → {url}")
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка запроса: {e}")
            return None

    def full_url(self, href: str) -> str:
        """Превращает относительный путь в абсолютный URL."""
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return self.base_url.rstrip("/") + "/" + href.lstrip("/")

    async def get_tasks(self, session: aiohttp.ClientSession, url: str) -> list:
        """
        Возвращает список словарей:
        {id, title, description, budget, date, url}
        """
        raise NotImplementedError
