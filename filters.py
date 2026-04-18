"""
Фильтрация сообщений по ключевым словам.
"""

import re
import storage

MIN_MESSAGE_LENGTH = 20  # Короче — игнорируем (скорее всего не заказ)

# ─── Паттерны для поиска контактов ───────────────────────────────────────────

_CONTACT_PATTERNS = [
    # Ссылки
    re.compile(r"https?://[^\s]+", re.IGNORECASE),
    # Telegram: @username или t.me/...
    re.compile(r"(?:@[a-zA-Z0-9_]{3,}|t\.me/[^\s]+)", re.IGNORECASE),
    # Телефон: +7, 8, международный формат
    re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    re.compile(r"\+\d{1,3}[\s\-]?\d[\d\s\-]{7,}"),
    # Email
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"),
    # WhatsApp / Viber упоминание рядом с цифрами
    re.compile(r"(?:whatsapp|viber|вотсап|вайбер)[\s:]*[\+\d][\d\s\-]{7,}", re.IGNORECASE),
]


def find_contacts(text: str) -> list:
    """Ищет контактные данные в тексте. Возвращает список найденных."""
    found = []
    for pattern in _CONTACT_PATTERNS:
        matches = pattern.findall(text)
        found.extend(matches)
    return found


def has_contacts(text: str) -> bool:
    """Есть ли в тексте хоть один контакт."""
    return any(p.search(text) for p in _CONTACT_PATTERNS)


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
