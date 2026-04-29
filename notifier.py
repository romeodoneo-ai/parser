"""
Форматирование и отправка уведомлений через бота.
"""

from datetime import datetime


def format_notification(
    channel_display: str,
    text: str,
    matched_keywords,
    message_link=None,
    user_link=None,
) -> str:
    """Собирает красивую карточку для уведомления."""

    preview = text.strip()
    if len(preview) > 700:
        preview = preview[:700] + "…"

    keywords_str = "  ".join(f"#{kw.replace(' ', '_')}" for kw in matched_keywords)
    time_str = datetime.now().strftime("%H:%M · %d.%m.%Y")

    lines = [
        "🔔 **Новый заказ**",
        "",
        f"📍 {channel_display}",
        f"🕐 {time_str}",
        f"🏷 {keywords_str}",
        "",
        "─" * 30,
        preview,
        "─" * 30,
    ]

    link_parts = []
    if message_link:
        link_parts.append(f"[🔗 Сообщение]({message_link})")
    if user_link:
        link_parts.append(f"[💬 Написать]({user_link})")
    if link_parts:
        lines.append("\n" + "  ·  ".join(link_parts))

    return "\n".join(lines)
