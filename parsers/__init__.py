from .fl import FlParser
from .pchel import PchelParser
from .freelancejob import FreelancejobParser
from .freelance_ru import FreelanceRuParser
from .weblancer import WeblancerParser
from .youdo import YoudoParser

# Реестр парсеров: домен → класс
REGISTRY = {
    "fl.ru":           FlParser,
    "pchel.net":       PchelParser,
    "freelancejob.ru": FreelancejobParser,
    "freelance.ru":    FreelanceRuParser,
    "weblancer.net":   WeblancerParser,
    "youdo.com":       YoudoParser,
}

def get_parser(url: str):
    """Возвращает нужный парсер по URL сайта или None."""
    for domain, cls in REGISTRY.items():
        if domain in url:
            return cls()
    return None
