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
/status — статистика и состояние
/recent — последние 5 находок
/report 24h — отчёт за период (1h 6h 12h 24h 3d 7d)

**Каналы**
/channels — список каналов
/add @channel1, @channel2 — добавить
/remove @channel1, @channel2 — убрать

**Ключевые слова**
/keywords — список слов
/add_kw слово1, слово2 — добавить
/remove_kw слово1, слово2 — убрать

**Слова-исключения**
/excludes — список исключений
/add_ex слово1, слово2 — добавить
/remove_ex слово1, слово2 — убрать

**Сайты**
/sites — список сайтов
/add_site Название https://... 20 — добавить (20 = минуты)
/remove_site Название — убрать по названию
/remove_site https://... — убрать по ссылке
/site_raw_on Название — все заказы без фильтров
/site_raw_off Название — вернуть фильтры

**Фильтры**
/contacts — все настройки фильтрации
/web_kw_on — ключевые слова для сайтов вкл
/web_kw_off — ключевые слова для сайтов выкл
/contacts_web_on — контакты для сайтов вкл
/contacts_web_off — контакты для сайтов выкл
/contacts_tg_on — контакты для Telegram вкл
/contacts_tg_off — контакты для Telegram выкл

**Управление**
/pause — приостановить
/resume — возобновить
/reset_web — сбросить историю веб-заказов (перепроверить заново)
/test — проверить что бот работает
/getid — узнать ID закрытого канала

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
        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/add\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_add_channel(event):
            raw = event.pattern_match.group(1).strip()
            channels = [c.strip() for c in re.split(r"[,\n]+", raw) if c.strip()]
            for ch in channels:
                storage.add_channel(ch)
            if len(channels) == 1:
                await event.respond(f"✅ Канал **{channels[0]}** добавлен.", parse_mode="md")
            else:
                lines = "\n".join(f"• {ch}" for ch in channels)
                await event.respond(f"✅ Добавлено каналов **{len(channels)}**:\n\n{lines}", parse_mode="md")
            logger.info(f"Добавлены каналы: {channels}")

        # ── /remove @channel ─────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/remove\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_remove_channel(event):
            raw = event.pattern_match.group(1).strip()
            channels = [c.strip() for c in re.split(r"[,\n]+", raw) if c.strip()]
            removed, not_found = [], []
            for ch in channels:
                if storage.remove_channel(ch):
                    removed.append(ch)
                else:
                    not_found.append(ch)
            text = ""
            if removed:
                lines = "\n".join(f"• {ch}" for ch in removed)
                text += f"✅ Удалено **{len(removed)}**:\n{lines}"
            if not_found:
                lines = "\n".join(f"• {ch}" for ch in not_found)
                text += f"\n\n❌ Не найдено:\n{lines}"
            await event.respond(text.strip(), parse_mode="md")

        # ── /keywords ────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/keywords$"))
        async def cmd_keywords(event):
            keywords = storage.get_keywords()
            if not keywords:
                await event.respond(
                    "Список ключевых слов пуст.\n\nДобавьте: `/add_kw слово`", parse_mode="md"
                )
                return
            # Разбиваем на части по 50 слов чтобы не превысить лимит Telegram
            chunk_size = 50
            chunks = [keywords[i:i+chunk_size] for i in range(0, len(keywords), chunk_size)]
            await event.respond(
                f"🔑 **Ключевые слова** — всего {len(keywords)} шт. "
                f"({'1 часть' if len(chunks) == 1 else f'{len(chunks)} части'}):",
                parse_mode="md",
            )
            for i, chunk in enumerate(chunks, 1):
                lines = "\n".join(f"• {kw}" for kw in chunk)
                header = f"**Часть {i}/{len(chunks)}:**\n\n" if len(chunks) > 1 else ""
                await self.bot.send_message(uid, header + lines, parse_mode="md")

        # ── /add_kw слово ────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/add_kw\s+([\s\S]+)", re.IGNORECASE)))
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
        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/remove_kw\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_remove_kw(event):
            raw = event.pattern_match.group(1).strip()
            keywords = [k.strip() for k in re.split(r"[,\n]+", raw) if k.strip()]
            removed, not_found = [], []
            for kw in keywords:
                if storage.remove_keyword(kw):
                    removed.append(kw)
                else:
                    not_found.append(kw)
            text = ""
            if removed:
                lines = "\n".join(f"• {kw}" for kw in removed)
                text += f"✅ Удалено **{len(removed)}**:\n{lines}"
            if not_found:
                lines = "\n".join(f"• {kw}" for kw in not_found)
                text += f"\n\n❌ Не найдено:\n{lines}"
            await event.respond(text.strip(), parse_mode="md")

        # ── Фильтр контактов ─────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/contacts$"))
        async def cmd_contacts_status(event):
            web_contacts = "✅ вкл" if storage.contacts_filter_web_enabled() else "❌ выкл"
            tg_contacts  = "✅ вкл" if storage.contacts_filter_tg_enabled()  else "❌ выкл"
            web_kw       = "✅ вкл" if storage.web_keywords_enabled()         else "❌ выкл"
            await event.respond(
                f"⚙️ **Настройки фильтрации сайтов**\n\n"
                f"🔑 Ключевые слова: {web_kw}\n"
                f"📞 Фильтр контактов: {web_contacts}\n"
                f"/web_kw_on — /web_kw_off\n"
                f"/contacts_web_on — /contacts_web_off\n\n"
                f"⚙️ **Настройки фильтрации Telegram**\n\n"
                f"📞 Фильтр контактов: {tg_contacts}\n"
                f"/contacts_tg_on — /contacts_tg_off\n\n"
                "Фильтр контактов — приходят только заявки где есть:\n"
                "ссылка, @telegram, телефон или email",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/web_kw_on$"))
        async def cmd_web_kw_on(event):
            storage.set_web_keywords(True)
            await event.respond(
                "✅ Ключевые слова для сайтов **включены**.\n"
                "Присылаются только совпадения по ключевым словам.",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/web_kw_off$"))
        async def cmd_web_kw_off(event):
            storage.set_web_keywords(False)
            await event.respond(
                "❌ Ключевые слова для сайтов **выключены**.\n"
                "Присылаются все обновления страниц (только контакты, если фильтр включён).",
                parse_mode="md",
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/contacts_web_on$"))
        async def cmd_contacts_web_on(event):
            storage.set_contacts_filter_web(True)
            await event.respond("✅ Фильтр контактов для **сайтов** включён.", parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/contacts_web_off$"))
        async def cmd_contacts_web_off(event):
            storage.set_contacts_filter_web(False)
            await event.respond("❌ Фильтр контактов для **сайтов** выключен.", parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/contacts_tg_on$"))
        async def cmd_contacts_tg_on(event):
            storage.set_contacts_filter_tg(True)
            await event.respond("✅ Фильтр контактов для **Telegram** включён.", parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/contacts_tg_off$"))
        async def cmd_contacts_tg_off(event):
            storage.set_contacts_filter_tg(False)
            await event.respond("❌ Фильтр контактов для **Telegram** выключен.", parse_mode="md")

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

        # ── Слова-исключения ─────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/excludes$"))
        async def cmd_excludes(event):
            keywords = storage.get_excluded_keywords()
            if not keywords:
                await event.respond(
                    "Слов-исключений нет.\n\nДобавить: `/add_ex слово1, слово2`",
                    parse_mode="md",
                )
                return
            chunk_size = 50
            chunks = [keywords[i:i+chunk_size] for i in range(0, len(keywords), chunk_size)]
            await event.respond(
                f"🚫 **Слова-исключения** — всего {len(keywords)} шт.\n"
                "Сообщения с этими словами не присылаются.",
                parse_mode="md",
            )
            for i, chunk in enumerate(chunks, 1):
                lines = "\n".join(f"• {kw}" for kw in chunk)
                header = f"**Часть {i}/{len(chunks)}:**\n\n" if len(chunks) > 1 else ""
                await self.bot.send_message(uid, header + lines, parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/add_ex\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_add_ex(event):
            raw = event.pattern_match.group(1).strip()
            keywords = [k.strip() for k in re.split(r"[,\n]+", raw) if k.strip()]
            for kw in keywords:
                storage.add_excluded_keyword(kw)
            if len(keywords) == 1:
                await event.respond(f"🚫 Исключение **«{keywords[0]}»** добавлено.", parse_mode="md")
            else:
                lines = "\n".join(f"• {kw}" for kw in keywords)
                await event.respond(f"🚫 Добавлено исключений **{len(keywords)}**:\n\n{lines}", parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/remove_ex\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_remove_ex(event):
            raw = event.pattern_match.group(1).strip()
            keywords = [k.strip() for k in re.split(r"[,\n]+", raw) if k.strip()]
            removed, not_found = [], []
            for kw in keywords:
                if storage.remove_excluded_keyword(kw):
                    removed.append(kw)
                else:
                    not_found.append(kw)
            text = ""
            if removed:
                lines = "\n".join(f"• {kw}" for kw in removed)
                text += f"✅ Удалено **{len(removed)}**:\n{lines}"
            if not_found:
                lines = "\n".join(f"• {kw}" for kw in not_found)
                text += f"\n\n❌ Не найдено:\n{lines}"
            await event.respond(text.strip(), parse_mode="md")

        # ── Сайты ────────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/sites$"))
        async def cmd_sites(event):
            sites = storage.get_websites()
            if not sites:
                await event.respond(
                    "Сайтов нет.\n\n"
                    "Добавить:\n`/add_site Название https://example.com 20`\n"
                    "(20 — интервал проверки в минутах)\n\n"
                    "Можно несколько сразу — каждый с новой строки.",
                    parse_mode="md",
                )
                return
            lines = []
            for s in sites:
                raw_tag = "  🔓 **все заказы**" if s.get("raw_mode") else ""
                lines.append(f"• **{s['name']}** — каждые {s['interval_minutes']} мин.{raw_tag}\n  {s['url']}")
            await event.respond(
                f"🌐 **Отслеживаемые сайты** ({len(sites)}):\n\n" + "\n\n".join(lines) +
                "\n\nДобавить: `/add_site Название https://... 20`"
                "\nУбрать: `/remove_site Название`"
                "\nВсе заказы без фильтров: `/site_raw_on Название`"
                "\nВернуть фильтры: `/site_raw_off Название`",
                parse_mode="md",
                link_preview=False,
            )

        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/add_site\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_add_site(event):
            raw = event.pattern_match.group(1).strip()
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            added, errors = [], []
            for line in lines:
                # Формат: Название https://url.com 20
                m = re.match(r"^(.+?)\s+(https?://\S+)(?:\s+(\d+))?$", line)
                if m:
                    name = m.group(1).strip()
                    url = m.group(2).strip()
                    minutes = int(m.group(3) or 20)
                    storage.add_website(url, name, minutes)
                    added.append(f"**{name}** — каждые {minutes} мин.")
                else:
                    errors.append(f"• `{line}` — неверный формат")
            text = ""
            if added:
                text += "✅ Добавлено:\n" + "\n".join(f"• {a}" for a in added)
            if errors:
                text += "\n\n❌ Ошибки (формат: Название https://... 20):\n" + "\n".join(errors)
            await event.respond(text.strip(), parse_mode="md")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=re.compile(r"^/remove_site\s+([\s\S]+)", re.IGNORECASE)))
        async def cmd_remove_site(event):
            raw = event.pattern_match.group(1).strip()
            items = [i.strip() for i in re.split(r"[,\n]+", raw) if i.strip()]
            removed, not_found = [], []
            for item in items:
                # Пробуем удалить по URL или по названию
                if storage.remove_website(item) or storage.remove_website_by_name(item):
                    removed.append(item)
                else:
                    not_found.append(item)
            text = ""
            if removed:
                text += "✅ Удалено:\n" + "\n".join(f"• {i}" for i in removed)
            if not_found:
                text += "\n\n❌ Не найдено:\n" + "\n".join(f"• {i}" for i in not_found)
            await event.respond(text.strip(), parse_mode="md")

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

        # ── /reset_web ────────────────────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/reset_web$"))
        async def cmd_reset_web(event):
            storage.clear_seen_web_tasks()
            await event.respond(
                "🔄 История просмотренных веб-заказов **сброшена**.\n\n"
                "На следующей проверке все заказы будут проанализированы заново.",
                parse_mode="md",
            )

        # ── /site_raw_on /site_raw_off ────────────────────────────
        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/site_raw_on (.+)$"))
        async def cmd_site_raw_on(event):
            name = event.pattern_match.group(1).strip()
            if storage.set_site_raw_mode(name, True):
                await event.respond(
                    f"🔓 Сайт **{name}**: режим **все заказы** включён.\n"
                    f"Все новые заказы будут отправляться без фильтров по ключевым словам и контактам.",
                    parse_mode="md",
                )
            else:
                await event.respond(f"❌ Сайт «{name}» не найден. Проверь название через /sites")

        @self.bot.on(events.NewMessage(from_users=uid, pattern=r"^/site_raw_off (.+)$"))
        async def cmd_site_raw_off(event):
            name = event.pattern_match.group(1).strip()
            if storage.set_site_raw_mode(name, False):
                await event.respond(
                    f"🔒 Сайт **{name}**: фильтры **возвращены**.",
                    parse_mode="md",
                )
            else:
                await event.respond(f"❌ Сайт «{name}» не найден. Проверь название через /sites")

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
