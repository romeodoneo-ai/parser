#!/bin/bash
# Установка парсера на чистый VPS (Ubuntu/Debian)
# Запуск: bash vps_setup.sh

set -e  # Остановиться если любая команда упала

echo ""
echo "================================================"
echo "   Установка Telegram Parser на VPS"
echo "================================================"
echo ""

# ── 1. Смена пароля root ─────────────────────────────────────────────────────
echo "🔐 Сначала сменим пароль root."
echo "   Введите новый пароль (символы не отображаются — это нормально):"
passwd root
echo "✅ Пароль root изменён."
echo ""

# ── 2. Обновление системы ────────────────────────────────────────────────────
echo "📦 Обновляем систему..."
apt update -qq && apt upgrade -y -qq
echo "✅ Система обновлена."
echo ""

# ── 3. Установка Python, pip, git ────────────────────────────────────────────
echo "🐍 Устанавливаем Python, pip, git..."
apt install -y -qq python3 python3-pip git
echo "✅ Python $(python3 --version), git $(git --version | cut -d' ' -f3) установлены."
echo ""

# ── 4. Клонирование репозитория ──────────────────────────────────────────────
echo "📂 Клонируем репозиторий..."
cd /root
if [ -d "parser" ]; then
    echo "   Папка parser уже есть — обновляем..."
    cd parser && git pull
else
    git clone https://github.com/romeodoneo-ai/parser.git
    cd parser
fi
echo "✅ Код загружен в /root/parser"
echo ""

# ── 5. Установка зависимостей Python ────────────────────────────────────────
echo "📚 Устанавливаем зависимости..."
pip3 install -q -r requirements.txt
echo "✅ Зависимости установлены."
echo ""

# ── 6. Создание config.yaml ──────────────────────────────────────────────────
if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    chmod 600 config.yaml  # Только root может читать — защита ключей
    echo "📝 Создан config.yaml (права доступа: только root)"
    echo ""
    echo "⚠️  ВАЖНО: Заполните config.yaml вашими данными:"
    echo "   nano /root/parser/config.yaml"
else
    echo "✅ config.yaml уже существует — пропускаем."
fi
echo ""

# ── 7. Настройка автозапуска (systemd) ───────────────────────────────────────
echo "⚙️  Настраиваем автозапуск..."
cp /root/parser/parser.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable parser
echo "✅ Автозапуск настроен."
echo ""

# ── Итог ─────────────────────────────────────────────────────────────────────
echo "================================================"
echo "   Установка завершена!"
echo "================================================"
echo ""
echo "Следующие шаги:"
echo ""
echo "  1. Заполните конфиг:"
echo "     nano /root/parser/config.yaml"
echo ""
echo "  2. Запустите один раз вручную для авторизации:"
echo "     cd /root/parser && python3 main.py"
echo "     (введите телефон и код из Telegram, затем Ctrl+C)"
echo ""
echo "  3. Запустите как службу:"
echo "     systemctl start parser"
echo ""
echo "  4. Проверьте что работает:"
echo "     systemctl status parser"
echo ""
echo "  Полезные команды:"
echo "     systemctl stop parser      — остановить"
echo "     systemctl restart parser   — перезапустить"
echo "     journalctl -u parser -f    — смотреть логи"
echo ""
