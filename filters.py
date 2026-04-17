"""
Фильтрация сообщений по ключевым словам.
"""

import storage

MIN_MESSAGE_LENGTH = 20  # Короче — игнорируем (скорее всего не заказ)


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
