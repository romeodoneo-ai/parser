"""
Мониторинг сайтов.
Для сайтов с парсером — вытаскивает каждый заказ отдельно.
Для остальных — отслеживает изменения страницы (старый режим).
"""

import asyncio
import hashlib
import logging

import aiohttp
from bs4 import BeautifulSoup

import storage
import filters
from parsers import get_parser

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


async def fetch_full_text(session, url: str) -> str:
    """Загружает страницу заказа и возвращает чистый текст (без HTML-тегов)."""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return ""
            html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link"]):
            tag.decompose()
        return " ".join(soup.get_text(" ").split())
    except Exception as e:
        logger.debug(f"Не удалось загрузить детали заказа {url}: {e}")
        return ""


def format_task_notification(task: dict, site_name: str, contacts: str = "") -> str:
    """Форматирует карточку найденного заказа."""
    lines = [f"🔔 **Новый заказ — {site_name}**", ""]

    lines.append(f"📌 **{task['title']}**")

    if task.get("budget"):
        lines.append(f"💰 {task['budget']}")

    if task.get("date"):
        lines.append(f"📅 {task['date']}")

    if task.get("description"):
        desc = task["description"].strip()
        if len(desc) > 500:
            desc = desc[:500] + "…"
        lines.append("")
        lines.append(desc)

    if contacts:
        lines.append("")
        lines.append(f"📞 {contacts}")

    lines.append("")
    lines.append(f"[🔗 Открыть заказ]({task['url']})")

    return "\n".join(lines)


async def check_with_parser(session, site: dict, parser, bot_client, user_id: int):
    """Проверяет сайт через специализированный парсер — по одному заказу."""
    url  = site["url"]
    name = site["name"]

    raw_mode     = bool(site.get("raw_mode", False))
    need_contacts = storage.contacts_filter_web_enabled() and not raw_mode
    need_keywords = storage.web_keywords_enabled() and not raw_mode

    try:
        tasks = await parser.get_tasks(session, url)

        if not tasks:
            logger.info(f"[{name}] Заказов не найдено (парсер вернул пустой список).")
            return

        new_count = 0
        for task in tasks:
            task_url = task.get("url", "")
            if not task_url:
                continue

            # Уже видели этот заказ?
            if storage.is_web_task_seen(task_url):
                continue

            storage.mark_web_task_seen(task_url, name)
            new_count += 1

            # Если описание пустое — подгружаем страницу задания
            if not task.get("description") and task_url:
                await asyncio.sleep(0.5)
                detail_text = await fetch_full_text(session, task_url)
                if detail_text and len(detail_text) > 50:
                    task = dict(task)
                    task["description"] = detail_text[:500]

            # Текст с листинга (короткий)
            listing_text = (task.get("title", "") + " " + task.get("description", "")).strip()

            # Если нужны контакты, но в листинге их нет — загружаем страницу заказа
            if need_contacts and not filters.has_contacts(listing_text):
                await asyncio.sleep(0.8)
                detail_text = await fetch_full_text(session, task_url)
                text = detail_text if len(detail_text) > len(listing_text) else listing_text
            else:
                text = listing_text

            # Фильтр по ключевым словам (если включён)
            if need_keywords:
                matched, keywords = filters.is_match(text)
                if not matched:
                    # Попробуем ещё раз с детальной страницей, если не загружали
                    if text == listing_text and task_url:
                        await asyncio.sleep(0.8)
                        detail_text = await fetch_full_text(session, task_url)
                        if detail_text:
                            matched, keywords = filters.is_match(detail_text)
                            if matched:
                                text = detail_text
                    if not matched:
                        continue
            else:
                _, keywords = filters.is_match(text)

            # Фильтр контактов (если включён)
            if need_contacts and not filters.has_contacts(text):
                logger.debug(f"[{name}] Нет контактов: {task.get('title', '')[:50]}")
                continue

            # Собираем найденные контакты для уведомления
            contacts_str = filters.extract_contact_context(text)

            # Сохраняем и отправляем
            storage.save_match(task_url, None, listing_text[:500], keywords or ["веб"])
            notification = format_task_notification(task, name, contacts_str)

            await bot_client.send_message(user_id, notification, parse_mode="md", link_preview=False)
            logger.info(f"[{name}] ✅ Новый заказ: {task.get('title', '')[:60]}")

        logger.info(f"[{name}] Проверено {len(tasks)} заказов, новых: {new_count}")

    except Exception as e:
        logger.error(f"[{name}] Ошибка парсера: {e}", exc_info=True)


async def check_generic(session, site: dict, bot_client, user_id: int):
    """Старый режим — отслеживает изменения страницы целиком."""
    url  = site["url"]
    name = site["name"]

    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                logger.warning(f"[{name}] HTTP {resp.status}")
                return
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())

        new_hash = hashlib.md5(text.encode()).hexdigest()
        old_hash = storage.get_web_hash(url)

        if old_hash is None:
            storage.set_web_hash(url, new_hash)
            logger.info(f"[{name}] Первая проверка — запомнили содержимое.")
            return

        if old_hash == new_hash:
            logger.info(f"[{name}] Изменений нет.")
            return

        storage.set_web_hash(url, new_hash)

        if storage.web_keywords_enabled():
            matched, keywords = filters.is_match(text)
            if not matched:
                logger.info(f"[{name}] Страница изменилась, ключевых слов нет.")
                return
        else:
            _, keywords = filters.is_match(text)
            keywords = keywords or ["обновление"]

        if storage.contacts_filter_web_enabled() and not filters.has_contacts(text):
            logger.info(f"[{name}] Нет контактов — пропускаем.")
            return

        snippet = text[:600] + "…" if len(text) > 600 else text
        storage.save_match(url, None, snippet, keywords)

        notification = (
            f"🔔 **Обновление — {name}**\n\n"
            f"🏷 {' '.join(f'#{k}' for k in keywords)}\n\n"
            f"{snippet}\n\n"
            f"[🔗 Открыть]({url})"
        )
        await bot_client.send_message(user_id, notification, parse_mode="md", link_preview=False)

    except Exception as e:
        logger.error(f"[{name}] Ошибка: {e}")


async def test_site(site: dict) -> str:
    """
    Запускает парсер для сайта прямо сейчас, игнорирует seen-список и фильтры.
    Возвращает готовый текст для отправки в Telegram.
    """
    url    = site["url"]
    name   = site["name"]
    parser = get_parser(url)

    lines = [f"🔬 **Тест парсера — {name}**\n"]

    if not parser:
        lines.append("⚠️ Специализированного парсера нет — используется generic-режим.")
        lines.append(f"URL: {url}")
        return "\n".join(lines)

    lines.append(f"🔧 Парсер: `{parser.__class__.__name__}`")
    lines.append(f"🔗 URL: {url}\n")

    try:
        async with aiohttp.ClientSession() as session:
            tasks = await parser.get_tasks(session, url)
    except Exception as e:
        lines.append(f"❌ Ошибка парсера: {e}")
        return "\n".join(lines)

    if not tasks:
        lines.append("❌ **Парсер вернул 0 заказов.**")
        lines.append("")
        lines.append("Возможные причины:")
        lines.append("• Playwright не установлен на сервере (`pip install playwright && playwright install chromium`)")
        lines.append("• Сайт изменил HTML-структуру")
        lines.append("• Сайт блокирует запросы (нужен proxy)")
        return "\n".join(lines)

    lines.append(f"✅ Найдено заказов: **{len(tasks)}**\n")
    lines.append("**Первые 5:**\n")

    for i, t in enumerate(tasks[:5], 1):
        title = (t.get("title") or "—")[:80]
        budget = t.get("budget") or ""
        desc   = (t.get("description") or "")[:100]
        url_t  = t.get("url") or ""
        lines.append(f"{i}. **{title}**")
        if budget:
            lines.append(f"   💰 {budget}")
        if desc:
            lines.append(f"   {desc}")
        lines.append(f"   {url_t}")
        lines.append("")

    return "\n".join(lines)


class WebMonitor:
    def __init__(self, config: dict, bot_client, paused_ref):
        self.config     = config
        self.bot_client = bot_client
        self.paused_ref = paused_ref
        self.user_id    = config["telegram"]["your_user_id"]

        # Загружаем сайты из config.yaml в БД
        for site in config.get("websites", []):
            storage.add_website(site["url"], site["name"], site.get("interval_minutes", 10))

    async def run(self):
        logger.info("Веб-мониторинг запущен.")
        last_checked = {}

        async with aiohttp.ClientSession() as session:
            while True:
                await asyncio.sleep(60)

                if self.paused_ref():
                    continue

                sites = storage.get_websites()
                now   = asyncio.get_event_loop().time()

                for site in sites:
                    url          = site["url"]
                    interval_sec = site["interval_minutes"] * 60
                    last         = last_checked.get(url, 0)

                    if now - last < interval_sec:
                        continue

                    last_checked[url] = now
                    parser = get_parser(url)

                    if parser:
                        await check_with_parser(session, site, parser, self.bot_client, self.user_id)
                    else:
                        await check_generic(session, site, self.bot_client, self.user_id)
