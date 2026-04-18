"""
Точка входа. Запускает мониторинг каналов и бота управления.
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from telethon import TelegramClient

import storage
from monitor import Monitor
from manager_bot import ManagerBot
from web_monitor import WebMonitor

# ─── Папки создаём до всего остального ──────────────────────────────────────
Path("data").mkdir(exist_ok=True)
Path("sessions").mkdir(exist_ok=True)

# ─── Логи ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    path = Path("config.yaml")
    if not path.exists():
        logger.error("Файл config.yaml не найден! Создайте его по образцу.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_config(cfg: dict):
    tg = cfg.get("telegram", {})
    problems = []
    if str(tg.get("api_id", "")).startswith("1234"):
        problems.append("api_id не заполнен (замените 12345678 на свой)")
    if "ВАШ" in str(tg.get("api_hash", "")):
        problems.append("api_hash не заполнен")
    if "ВАШ" in str(tg.get("bot_token", "")):
        problems.append("bot_token не заполнен")
    if tg.get("your_user_id") in (None, 123456789):
        problems.append("your_user_id не заполнен (узнать у @userinfobot)")
    if problems:
        logger.error("config.yaml не настроен:")
        for p in problems:
            logger.error(f"  • {p}")
        logger.error("Откройте config.yaml и заполните нужные поля.")
        sys.exit(1)


async def main():
    cfg = load_config()
    validate_config(cfg)

    # Папки
    Path("data").mkdir(exist_ok=True)
    Path("sessions").mkdir(exist_ok=True)

    # База данных
    storage.init_db()

    # Загружаем каналы и ключевые слова из config.yaml только при первом запуске
    # (когда база ещё пустая — чтобы не затирать изменения сделанные через бота)
    if not storage.get_channels() and not storage.get_keywords():
        logger.info("Первый запуск — загружаем каналы и слова из config.yaml...")
        for ch in cfg.get("channels", []):
            storage.add_channel(ch)
        for kw in cfg.get("keywords", []):
            storage.add_keyword(kw)

    tg = cfg["telegram"]

    # Прокси (нужен если VPS в России)
    proxy = None
    if tg.get("proxy"):
        p = tg["proxy"]
        import socks
        proxy = (socks.SOCKS5, p["host"], p["port"])
        if p.get("username"):
            proxy = (socks.SOCKS5, p["host"], p["port"], True, p["username"], p["password"])
        logger.info(f"Прокси: {p['host']}:{p['port']}")

    # Клиент вашего аккаунта — слушает каналы
    user_client = TelegramClient(
        "sessions/user",
        tg["api_id"],
        tg["api_hash"],
        proxy=proxy,
    )

    # Бот заказов — только присылает найденные заявки
    notify_client = TelegramClient(
        "sessions/notify_bot",
        tg["api_id"],
        tg["api_hash"],
        proxy=proxy,
    )

    # Бот настроек — принимает команды управления
    manager_client = TelegramClient(
        "sessions/manager_bot",
        tg["api_id"],
        tg["api_hash"],
        proxy=proxy,
    )

    logger.info("Подключение к Telegram…")
    await user_client.start()
    await notify_client.start(bot_token=tg["bot_token"])

    # Если manager_bot_token не задан — используем тот же бот
    manager_token = tg.get("manager_bot_token", "").strip()
    if manager_token and manager_token != "ТОКЕН_ВТОРОГО_БОТА":
        await manager_client.start(bot_token=manager_token)
        logger.info("Два бота запущены: заказы и настройки раздельно.")
    else:
        manager_client = notify_client
        logger.info("Один бот: и заказы, и настройки (manager_bot_token не задан).")

    me = await user_client.get_me()
    logger.info(f"Аккаунт: {me.first_name} (@{me.username})")
    logger.info(f"Каналов в слежке:  {len(storage.get_channels())}")
    logger.info(f"Ключевых слов:     {len(storage.get_keywords())}")

    # Создаём и настраиваем компоненты
    monitor = Monitor(cfg, user_client, notify_client)
    manager = ManagerBot(cfg, manager_client, monitor)
    web_monitor = WebMonitor(cfg, notify_client, lambda: monitor.paused)

    monitor.setup()
    manager.setup()

    # Приветственное сообщение
    try:
        await notify_client.send_message(
            tg["your_user_id"],
            "🔔 **Бот заказов запущен.** Сюда будут приходить найденные заявки.",
            parse_mode="md",
        )
        if manager_client != notify_client:
            await manager_client.send_message(
                tg["your_user_id"],
                "⚙️ **Бот настроек запущен.**\n\nОтправьте /help для списка команд.",
                parse_mode="md",
            )
    except Exception:
        pass

    logger.info("Мониторинг запущен. Ожидаем сообщения…")

    clients = [user_client.run_until_disconnected(), notify_client.run_until_disconnected(), web_monitor.run()]
    if manager_client != notify_client:
        clients.append(manager_client.run_until_disconnected())

    await asyncio.gather(*clients)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем.")
