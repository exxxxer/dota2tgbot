# DotaMetaBot

Telegram-бот для получения информации по Dota 2.

## Возможности

- /player ID — статистика игрока
- /match ID — информация о матче
- /hero имя — информация о герое
- /meta — список метовых героев
- /draft — анализ драфта
- /news — новости Dota 2 через HTML-скрапинг

## Используемые технологии

- Python
- aiogram
- OpenDota API
- BeautifulSoup
- requests
- dotenv

## Настройка

Создать файл .env:

BOT_TOKEN=токен_бота

## Запуск

pip install -r requirements.txt
python bot.py

Бот доступен по ссылке: https://t.me/d0t42m3t4bot
