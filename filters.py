"""
Фильтрация сообщений по ключевым словам.
"""

import storage

MIN_MESSAGE_LENGTH = 20  # Короче — игнорируем (скорее всего не заказ)


def find_keywords(text: str) -> list[str]:
    """Возвращает список найденных ключевых слов в тексте."""
    if not text:
        return []

    text_lower = text.lower()
    keywords = storage.get_keywords()

    return [kw for kw in keywords if kw.lower() in text_lower]


def is_match(text: str) -> tuple[bool, list[str]]:
    """
    Проверяет, является ли сообщение потенциальным заказом.
    Возвращает (подходит: bool, найденные_слова: list).
    """
    if not text or len(text.strip()) < MIN_MESSAGE_LENGTH:
        return False, []

    found = find_keywords(text)
    return len(found) > 0, found
