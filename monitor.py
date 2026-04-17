"""
Мониторинг каналов через Telethon.
Слушает все входящие сообщения и фильтрует по ключевым словам.
"""

import logging
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

import storage
import filters
from notifier import format_notification

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config: dict, user_client: TelegramClient, bot_client: TelegramClient):
        self.config = config
        self.user_client = user_client
        self.bot_client = bot_client
        self.your_user_id: int = config["telegram"]["your_user_id"]
        self.paused: bool = False

    def setup(self):
        """Регистрирует обработчик новых сообщений."""

        @self.user_client.on(events.NewMessage(incoming=True))
        async def handle(event):
            if self.paused:
                return
            await self._process(event)

        logger.info("Обработчик сообщений зарегистрирован")

    async def _process(self, event):
        try:
            chat = await event.get_chat()

            # Пропускаем личные переписки с людьми — только каналы и группы
            if isinstance(chat, User):
                return

            channel_username = getattr(chat, "username", None)
            channel_title = getattr(chat, "title", None) or "Без названия"
            chat_id = str(event.chat_id)

            # Проверяем, отслеживается ли этот канал/чат
            if not self._is_monitored(channel_username, chat_id):
                return

            msg_id = event.message.id

            # Пропускаем уже обработанные сообщения
            if storage.is_seen(chat_id, msg_id):
                return

            storage.mark_seen(chat_id, msg_id)

            text = event.message.message or ""
            matched, keywords = filters.is_match(text)

            if not matched:
                return

            # Формируем ссылку на оригинал
            message_link = None
            if channel_username:
                message_link = f"https://t.me/{channel_username}/{msg_id}"

            # Сохраняем находку в историю
            storage.save_match(chat_id, msg_id, text, keywords)

            # Отправляем уведомление
            channel_display = f"@{channel_username}" if channel_username else channel_title
            notification = format_notification(channel_display, text, keywords, message_link)

            await self.bot_client.send_message(
                self.your_user_id,
                notification,
                parse_mode="md",
                link_preview=False,
            )

            logger.info(f"[+] Заказ найден — {channel_display} | слова: {keywords}")

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)

    def _is_monitored(self, username, chat_id: str) -> bool:
        """Проверяет, есть ли канал в списке отслеживаемых."""
        monitored = storage.get_channels()
        for ch in monitored:
            ch_clean = ch.lstrip("@").lower()
            # Сравниваем по username
            if username and ch_clean == username.lower():
                return True
            # Сравниваем по числовому id (если канал добавлен по id)
            if ch_clean == chat_id:
                return True
        return False
