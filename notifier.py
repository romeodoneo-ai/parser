"""
Форматирование и отправка уведомлений через бота.
"""

from datetime import datetime


def format_notification(
    channel_display: str,
    text: str,
    matched_keywords: list[str],
    message_link: str | None = None,
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

    if message_link:
        lines.append(f"\n[🔗 Открыть в Telegram]({message_link})")

    return "\n".join(lines)
