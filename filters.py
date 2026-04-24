"""
Фильтрация сообщений по ключевым словам.
"""

import re
import storage

MIN_MESSAGE_LENGTH = 20  # Короче — игнорируем (скорее всего не заказ)

# ─── Паттерны для поиска контактов ───────────────────────────────────────────

_CONTACT_PATTERNS = [
    # Ссылки с http/https (включая соцсети, мессенджеры)
    re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE),
    # Ссылки с www. без схемы
    re.compile(r"\bwww\.[a-zA-Z0-9\-]{2,}\.[a-zA-Z]{2,}(?:/\S*)?", re.IGNORECASE),
    # Популярные домены без https: vk.com, wa.me, t.me, tg.me, discord.gg
    re.compile(r"\b(?:vk\.com|wa\.me|t\.me|tg\.me|discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE),
    # Telegram: @username
    re.compile(r"(?<!\w)@[a-zA-Z][a-zA-Z0-9_]{2,}", re.IGNORECASE),
    # Telegram shorthand: "тг: username" или "tg: @user"
    re.compile(r"(?:^|\s)(?:тг|tg)[\s:@]+[a-zA-Z0-9._\-]{3,}", re.IGNORECASE),
    # Телефон: +7 или 8 (российский)
    re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    # Телефон: международный формат
    re.compile(r"\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d[\d\s\-]{5,}"),
    # Email
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"),
    # WhatsApp / Viber с номером
    re.compile(
        r"(?:whatsapp|watsapp|вотсап|ватсап|вацап|вайбер|вибер|viber)[\s:]*[\+\d][\d\s\-\(\)]{6,}",
        re.IGNORECASE,
    ),
    # WhatsApp / Viber / Telegram / Skype / Discord упомянуты как способ связи
    re.compile(
        r"\b(?:whatsapp|watsapp|вотсап|ватсап|вацап|viber|вайбер|вибер"
        r"|skype|скайп|discord|дискорд|телеграм|telegram|телега)\b",
        re.IGNORECASE,
    ),
    # Skype логин: "skype: mylogin" или "скайп: mylogin"
    re.compile(r"(?:skype|скайп)[\s:]+[a-zA-Z0-9._\-]{3,}", re.IGNORECASE),
    # Instagram без https
    re.compile(r"\binstagram\.com/[a-zA-Z0-9_.]+", re.IGNORECASE),
    # Facebook без https
    re.compile(r"\bfacebook\.com/[a-zA-Z0-9_.]+", re.IGNORECASE),
    # VK без https: "вк: vk.com/..." или просто "vk.com/..."
    re.compile(r"\bvk\.com/[a-zA-Z0-9_.]+", re.IGNORECASE),
]


def find_contacts(text: str) -> list:
    """Ищет контактные данные в тексте. Возвращает список найденных (уникальных)."""
    found = []
    seen = set()
    for pattern in _CONTACT_PATTERNS:
        for m in pattern.findall(text):
            val = m.strip()
            if val and val.lower() not in seen:
                seen.add(val.lower())
                found.append(val)
    return found


def has_contacts(text: str) -> bool:
    """Есть ли в тексте хоть один контакт."""
    return any(p.search(text) for p in _CONTACT_PATTERNS)


def extract_contact_context(text: str, max_contacts: int = 5) -> str:
    """Возвращает строку с найденными контактами для показа в уведомлении."""
    contacts = find_contacts(text)
    if not contacts:
        return ""
    # Убираем слишком длинные (> 80 символов — вероятно мусор)
    contacts = [c for c in contacts if len(c) <= 80][:max_contacts]
    return "  |  ".join(contacts) if contacts else ""


def find_keywords(text: str):
    """Возвращает список найденных ключевых слов в тексте."""
    if not text:
        return []

    text_lower = text.lower()
    keywords = storage.get_keywords()

    return [kw for kw in keywords if kw.lower() in text_lower]


def has_exclusions(text: str) -> bool:
    """Возвращает True если в тексте есть слова-исключения."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in storage.get_excluded_keywords())


def is_match(text: str):
    """
    Проверяет, является ли сообщение потенциальным заказом.
    Возвращает (подходит: bool, найденные_слова: list).
    """
    if not text or len(text.strip()) < MIN_MESSAGE_LENGTH:
        return False, []

    # Сначала проверяем исключения — если есть, сразу отбрасываем
    if has_exclusions(text):
        return False, []

    found = find_keywords(text)
    return len(found) > 0, found
