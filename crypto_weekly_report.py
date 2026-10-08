#!/usr/bin/env python3
"""
Еженедельный отчёт по криптовалютам с отправкой в Telegram.

Скрипт получает данные с CoinGecko API, рассчитывает комбинированный
скоринг (капитализация + объём + рост за 7 дней), выбирает топ-10
и отправляет отчёт в Telegram-бот.

Работает как локально (через .env + Task Scheduler),
так и в GitHub Actions (через Secrets).
"""

import os
import sys
import math
import logging
from datetime import datetime

import requests

# python-dotenv нужен только для локального запуска.
# В GitHub Actions переменные приходят из Secrets, файла .env нет.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # в облаке dotenv не установлен — это нормально

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Веса для комбинированного скоринга
WEIGHT_MARKET_CAP = 0.40   # вес рыночной капитализации
WEIGHT_VOLUME = 0.30       # вес объёма торгов за 24ч
WEIGHT_CHANGE_7D = 0.30    # вес изменения цены за 7 дней

# Фильтры
MIN_MARKET_CAP = 50_000_000   # $50 млн
MIN_VOLUME = 1_000_000        # $1 млн

EXCLUDE_STABLECOINS = True
STABLECOIN_SYMBOLS = {
    "usdt", "usdc", "busd", "dai", "tusd", "usdp",
    "fdusd", "usdd", "gusd", "frax", "lusd", "usde"
}

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PARAMS = {
    "vs_currency": "usd",
    "order": "market_cap_desc",
    "per_page": 250,
    "page": 1,
    "sparkline": "false",
    "price_change_percentage": "7d"
}

# ---------------------------------------------------------------------------
# ЛОГИРОВАНИЕ
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crypto_report.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ---------------------------------------------------------------------------
# ФУНКЦИИ
# ---------------------------------------------------------------------------

def fetch_coins():
    """Получает список монет с рыночными данными с CoinGecko API."""
    try:
        resp = requests.get(COINGECKO_URL, params=COINGECKO_PARAMS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        logging.info("Получено %d монет с CoinGecko", len(data))
        return data
    except requests.RequestException as e:
        logging.error("Ошибка запроса к CoinGecko: %s", e)
        return None

def calculate_score(coin: dict) -> float:
    """Комбинированный скоринг: log(капитализация) + log(объём) + нормализованный рост."""
    mcap = coin.get("market_cap") or 0
    vol = coin.get("total_volume") or 0
    change = coin.get("price_change_percentage_7d_in_currency") or 0

    log_mcap = math.log10(mcap / 1_000_000) if mcap > 1_000_000 else 0
    log_vol = math.log10(vol / 1_000_000) if vol > 1_000_000 else 0
    norm_change = max(0.0, min(1.0, (change + 100) / 200))

    return (
        WEIGHT_MARKET_CAP * log_mcap +
        WEIGHT_VOLUME * log_vol +
        WEIGHT_CHANGE_7D * norm_change * 10
    )

def filter_and_rank(coins: list) -> list:
    """Фильтрует монеты и возвращает топ-10 по скорингу."""
    filtered = []
    for c in coins:
        if not c.get("market_cap") or not c.get("total_volume"):
            continue
        if c["market_cap"] < MIN_MARKET_CAP:
            continue
        if c["total_volume"] < MIN_VOLUME:
            continue
        if EXCLUDE_STABLECOINS and c.get("symbol", "").lower() in STABLECOIN_SYMBOLS:
            continue
        if c.get("price_change_percentage_7d_in_currency") is None:
            continue

        c["score"] = calculate_score(c)
        filtered.append(c)

    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:10]

def format_number(value: float, prefix: str = "$") -> str:
    """Форматирует число с суффиксами K, M, B, T."""
    if value >= 1_000_000_000_000:
        return f"{prefix}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:.2f}K"
    return f"{prefix}{value:,.2f}"

def format_price(price: float) -> str:
    """Форматирует цену в зависимости от её величины."""
    if price >= 1:
        return f"${price:,.2f}"
    if price >= 0.01:
        return f"${price:.4f}"
    return f"${price:.6f}"

def build_message(top_coins: list) -> str:
    """Формирует текст сообщения для Telegram в формате Markdown."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [
        "📊 *Еженедельный отчёт по криптовалютам*",
        f"_{now}_",
        "",
        "Топ-10 по комбинированному скорингу",
        "(капитализация + объём + рост за 7 дней):",
        ""
    ]

    for i, c in enumerate(top_coins, 1):
        name = c.get("name", "Unknown")
        symbol = c.get("symbol", "").upper()
        price = c.get("current_price", 0)
        change = c.get("price_change_percentage_7d_in_currency", 0)
        mcap = c.get("market_cap", 0)
        vol = c.get("total_volume", 0)

        change_icon = "🟢" if change >= 0 else "🔴"
        lines.append(f"*{i}. {name} ({symbol})*")
        lines.append(f"   💰 Цена: {format_price(price)}")
        lines.append(f"   {change_icon} 7д: {change:+.2f}%")
        lines.append(f"   🏦 Кап: {format_number(mcap)}")
        lines.append(f"   📈 Объём 24ч: {format_number(vol)}")
        lines.append(f"   ⭐ Скоринг: `{c['score']:.2f}`")
        lines.append("")

    lines.append("_Источник данных: CoinGecko_")
    return "\n".join(lines)

def send_telegram(message: str) -> bool:
    """Отправляет сообщение в Telegram через Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Не заданы TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logging.info("Сообщение успешно отправлено в Telegram")
        return True
    except requests.RequestException as e:
        logging.error("Ошибка отправки в Telegram: %s", e)
        return False

def main():
    """Основная логика скрипта."""
    logging.info("=== Запуск еженедельного отчёта ===")

    coins = fetch_coins()
    if not coins:
        logging.error("Не удалось получить данные. Завершение.")
        sys.exit(1)

    top = filter_and_rank(coins)
    if not top:
        logging.warning("Не найдено монет, удовлетворяющих фильтрам.")
        sys.exit(0)

    logging.info("Топ-10 монет:")
    for i, c in enumerate(top, 1):
        logging.info("  %d. %s (%s) — score=%.2f",
                     i, c["name"], c["symbol"].upper(), c["score"])

    message = build_message(top)

    if send_telegram(message):
        logging.info("Отчёт отправлен успешно.")
    else:
        logging.error("Отчёт не был отправлен.")
        sys.exit(1)

    logging.info("=== Завершение ===")

if __name__ == "__main__":
    main()
