"""
Бот-управление: принимает команды от вас и позволяет управлять мониторингом
прямо из Telegram, без перезапуска программы.
"""

import logging
import re
from telethon import TelegramClient, events

import storage

logger = logging.getLogger(__name__)

HELP_TEXT = """
👋 **Бот мониторинга заказов**

**Статус и статистика**
/status — показать статистику и состояние

**Каналы**
/channels — список отслеживаемых каналов
/add @channel — добавить канал
/remove @channel — убрать канал

**Ключевые слова**
/keywords — список ключевых слов
/add\\_kw слово — добавить ключевое слово
/remove\\_kw слово — убрать ключевое слово

**Сайты**
/sites — список сайтов
/add\\_site Название https://... 20 — добавить сайт (20 = минуты)
/remove\\_site https://... — убрать сайт

**Управление**
/pause — приостановить всё
/resume — возобновить
/recent — последние 5 находок

/help — показать эту справку
""".strip()


class ManagerBot:
    def __init__(self, config: dict, bot_client: TelegramClient, monitor):
        self.config = config
        self.bot = bot_client
        self.monitor = monitor
        self.your_user_id: int = config["telegram"]["your_user_id"]

    def setup(self):
        """Регистрирует все команды."""
        uid = self.your_user_id

        # ── /start и /help ──────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/(start|help)$"))
        async def cmd_help(event):
            await event.respond(HELP_TEXT, parse_mode="md")

        # ── /status ─────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/status$"))
        async def cmd_status(event):
            stats = storage.get_stats()
            channels = storage.get_channels()
            keywords = storage.get_keywords()
            state = "⏸ Приостановлен" if self.monitor.paused else "▶️ Работает"

            text = (
                f"**Состояние:** {state}\n\n"
                f"📊 **Статистика:**\n"
                f"• Проверено сообщений: {stats['total_seen']}\n"
                f"• Найдено заказов всего: {stats['total_matches']}\n"
                f"• Найдено сегодня: {stats['today_matches']}\n\n"
                f"📍 Каналов в слежке: **{len(channels)}**\n"
                f"🔑 Ключевых слов: **{len(keywords)}**"
            )
            await event.respond(text, parse_mode="md")

        # ── /channels ───────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/channels$"))
        async def cmd_channels(event):
            channels = storage.get_channels()
            if not channels:
                await event.respond(
                    "Список каналов пуст.\n\nДобавьте: `/add @channel`", parse_mode="md"
                )
                return
            lines = "\n".join(f"• {ch}" for ch in channels)
            await event.respond(
                f"📍 **Отслеживаемые каналы** ({len(channels)}):\n\n{lines}\n\n"
                "Убрать: `/remove @channel`",
                parse_mode="md",
            )

        # ── /add @channel ────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/add\s+(\S+)$"))
        async def cmd_add_channel(event):
            channel = event.pattern_match.group(1)
            storage.add_channel(channel)
            await event.respond(f"✅ Канал **{channel}** добавлен.", parse_mode="md")
            logger.info(f"Добавлен канал: {channel}")

        # ── /remove @channel ─────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/remove\s+(\S+)$"))
        async def cmd_remove_channel(event):
            channel = event.pattern_match.group(1)
            if storage.remove_channel(channel):
                await event.respond(f"✅ Канал **{channel}** удалён.", parse_mode="md")
                logger.info(f"Удалён канал: {channel}")
            else:
                await event.respond(
                    f"❌ Канал **{channel}** не найден в списке.", parse_mode="md"
                )

        # ── /keywords ────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/keywords$"))
        async def cmd_keywords(event):
            keywords = storage.get_keywords()
            if not keywords:
                await event.respond(
                    "Список ключевых слов пуст.\n\nДобавьте: `/add_kw слово`", parse_mode="md"
                )
                return
            lines = "\n".join(f"• {kw}" for kw in keywords)
            await event.respond(
                f"🔑 **Ключевые слова** ({len(keywords)}):\n\n{lines}\n\n"
                "Убрать: `/remove_kw слово`",
                parse_mode="md",
            )

        # ── /add_kw слово ────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/add_kw\s+(.+)$"))
        async def cmd_add_kw(event):
            raw = event.pattern_match.group(1).strip()
            # Разбиваем по запятым или переносам строк
            keywords = [k.strip() for k in re.split(r"[,\n]+", raw) if k.strip()]
            for kw in keywords:
                storage.add_keyword(kw)
            if len(keywords) == 1:
                await event.respond(f"✅ Слово **«{keywords[0]}»** добавлено.", parse_mode="md")
            else:
                lines = "\n".join(f"• {kw}" for kw in keywords)
                await event.respond(f"✅ Добавлено **{len(keywords)}** слов:\n\n{lines}", parse_mode="md")

        # ── /remove_kw слово ─────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/remove_kw\s+(.+)$"))
        async def cmd_remove_kw(event):
            keyword = event.pattern_match.group(1).strip()
            if storage.remove_keyword(keyword):
                await event.respond(f"✅ Слово **«{keyword}»** удалено.", parse_mode="md")
            else:
                await event.respond(
                    f"❌ Слово **«{keyword}»** не найдено.", parse_mode="md"
                )

        # ── /pause ────────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/pause$"))
        async def cmd_pause(event):
            if self.monitor.paused:
                await event.respond("Мониторинг уже приостановлен. /resume чтобы возобновить.")
            else:
                self.monitor.paused = True
                await event.respond("⏸ Мониторинг **приостановлен**.\n\n/resume — возобновить.", parse_mode="md")

        # ── /resume ───────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/resume$"))
        async def cmd_resume(event):
            if not self.monitor.paused:
                await event.respond("Мониторинг уже работает.")
            else:
                self.monitor.paused = False
                await event.respond("▶️ Мониторинг **возобновлён**.", parse_mode="md")

        # ── /report ──────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/report$"))
        async def cmd_report_help(event):
            await event.respond(
                "📋 **Отчёт за период**\n\n"
                "Укажите период:\n"
                "`/report 1h` — последний час\n"
                "`/report 6h` — последние 6 часов\n"
                "`/report 12h` — последние 12 часов\n"
                "`/report 24h` — последние сутки\n"
                "`/report 3d` — последние 3 дня\n"
                "`/report 7d` — последняя неделя",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/report (\d+)(h|d)$"))
        async def cmd_report(event):
            amount = int(event.pattern_match.group(1))
            unit = event.pattern_match.group(2)
            hours = amount if unit == "h" else amount * 24

            matches = storage.get_matches_since(hours)

            period_label = f"{amount} {'час' if unit == 'h' else 'дн'}{'а' if amount in (2,3,4) else 'ей' if amount > 4 else ''}"
            if unit == "h" and amount == 1:
                period_label = "час"

            if not matches:
                await event.respond(f"За последние {period_label} ничего не найдено.")
                return

            # Отправляем по одному сообщению на каждую находку (чтобы не превысить лимит)
            await event.respond(
                f"📋 **Отчёт за последние {period_label}** — найдено {len(matches)} заявок:",
                parse_mode="md",
            )

            for i, m in enumerate(matches, 1):
                dt = m["matched_at"][:16].replace("T", " ")
                preview = m["preview"][:400] + "…" if len(m["preview"]) > 400 else m["preview"]
                msg_id = m.get("message_id")

                # Пробуем собрать ссылку
                channel = m["channel"]
                link = ""
                if channel.startswith("-100"):
                    numeric_id = channel.replace("-100", "")
                    if msg_id:
                        link = f"\n[🔗 Открыть](https://t.me/c/{numeric_id}/{msg_id})"
                elif channel.startswith("@"):
                    if msg_id:
                        link = f"\n[🔗 Открыть](https://t.me/{channel.lstrip('@')}/{msg_id})"

                text = (
                    f"**{i}.** {channel} · {dt}\n"
                    f"🏷 {m['matched_keywords']}\n\n"
                    f"{preview}"
                    f"{link}"
                )
                await self.bot.send_message(uid, text, parse_mode="md", link_preview=False)

        # ── Сайты ────────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/sites$"))
        async def cmd_sites(event):
            sites = storage.get_websites()
            if not sites:
                await event.respond(
                    "Сайтов нет.\n\nДобавить:\n`/add_site Название https://example.com 20`\n(последнее число — интервал проверки в минутах)",
                    parse_mode="md",
                )
                return
            lines = [f"• [{s['name']}]({s['url']}) — каждые {s['interval_minutes']} мин." for s in sites]
            await event.respond(
                f"🌐 **Отслеживаемые сайты** ({len(sites)}):\n\n" + "\n".join(lines) +
                "\n\nУбрать: `/remove_site https://...`",
                parse_mode="md",
                link_preview=False,
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/add_site (.+?) (https?://\S+)(?: (\d+))?$"))
        async def cmd_add_site(event):
            name = event.pattern_match.group(1).strip()
            url = event.pattern_match.group(2).strip()
            minutes = int(event.pattern_match.group(3) or 20)
            storage.add_website(url, name, minutes)
            await event.respond(
                f"✅ Сайт **{name}** добавлен.\nПроверка каждые {minutes} минут.",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/remove_site (https?://\S+)$"))
        async def cmd_remove_site(event):
            url = event.pattern_match.group(1).strip()
            if storage.remove_website(url):
                await event.respond("✅ Сайт удалён.")
            else:
                await event.respond("❌ Сайт не найден.")

        # ── /getid ───────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/getid$"))
        async def cmd_getid(event):
            await event.respond(
                "Перешлите мне **любое сообщение** из нужного канала — я скажу его ID.",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, forwards=True))
        async def cmd_getid_forward(event):
            fwd = event.message.fwd_from
            if not fwd:
                return
            peer = getattr(fwd, "from_id", None)
            if peer is None:
                await event.respond("Не удалось определить ID — канал скрывает источник.")
                return
            chat_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)
            if chat_id:
                full_id = f"-100{chat_id}"
                await event.respond(
                    f"ID канала: `{full_id}`\n\nДобавить: `/add {full_id}`",
                    parse_mode="md",
                )
            else:
                await event.respond("Не удалось определить ID этого канала.")

        # ── /test ────────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/test$"))
        async def cmd_test(event):
            from notifier import format_notification
            fake = format_notification(
                "@test_channel",
                "Ищем опытного разработчика на React/Python для создания веб-приложения. "
                "Удалённо, долгосрочный проект. Бюджет обсуждается. Пишите в личку с портфолио.",
                ["разработчик", "react", "python", "удалённо"],
                "https://t.me/test",
            )
            await event.respond("✅ Бот работает! Вот как выглядит уведомление о заказе:\n\n" + fake, parse_mode="md")

        # ── /recent ───────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/recent$"))
        async def cmd_recent(event):
            matches = storage.get_recent_matches(5)
            if not matches:
                await event.respond("Пока ничего не найдено.")
                return
            lines = []
            for i, m in enumerate(matches, 1):
                dt = m["matched_at"][:16].replace("T", " ")
                lines.append(
                    f"**{i}. {m['channel']}** — {dt}\n"
                    f"🏷 {m['matched_keywords']}\n"
                    f"_{m['preview'][:150]}…_"
                )
            text = "📋 **Последние находки:**\n\n" + "\n\n".join(lines)
            await event.respond(text, parse_mode="md")

        logger.info("Команды бота зарегистрированы")
