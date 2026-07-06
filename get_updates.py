# -*- coding: utf-8 -*-
"""
Скрипт "Лог проекта -> дневная выжимка" — БЕСПЛАТНАЯ версия.

В отличие от версии с постоянно работающим ботом, этот скрипт не "живёт"
непрерывно. Он запускается один раз в день (через GitHub Actions по
расписанию — см. README.md), забирает все сообщения из чата "Лог проекта"
за последние сутки, аккуратно оформляет их в список и присылает тебе в
личку с ботом.

ИИ-обработки здесь НЕТ — это осознанно, чтобы не платить за API. Готовый
список сообщений ты сама вставляешь в обычный чат с Claude и просишь
оформить черновик отчёта (промпт — в README.md).

Как это технически возможно без сервера:
Telegram хранит непрочитанные ботом сообщения примерно 24 часа. Если
запускать этот скрипт раз в сутки, он успевает забрать всё, что накопилось,
через метод getUpdates. Чтобы не забирать одни и те же сообщения повторно,
скрипт запоминает "offset" (номер последнего обработанного сообщения) в
файле offset.json и коммитит его обновление обратно в репозиторий.
"""

import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
LOG_CHAT_ID = int(os.environ["LOG_CHAT_ID"])
REPORT_CHAT_ID = int(os.environ["REPORT_CHAT_ID"])
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Moscow")

OFFSET_FILE = "offset.json"
API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def load_offset() -> int:
    if not os.path.exists(OFFSET_FILE):
        return 0
    with open(OFFSET_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("offset", 0)


def save_offset(offset: int):
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


def fetch_updates(offset: int):
    """Забирает все накопленные сообщения, начиная с offset."""
    all_updates = []
    params = {"offset": offset + 1, "timeout": 0, "limit": 100}
    while True:
        resp = requests.get(f"{API_URL}/getUpdates", params=params, timeout=30)
        resp.raise_for_status()
        result = resp.json()["result"]
        if not result:
            break
        all_updates.extend(result)
        params["offset"] = result[-1]["update_id"] + 1
        if len(result) < 100:
            break
    return all_updates


def extract_text(msg: dict) -> str:
    parts = []
    if msg.get("text"):
        parts.append(msg["text"])
    if msg.get("caption"):
        parts.append(msg["caption"])
    if msg.get("document"):
        parts.append(f"[файл: {msg['document'].get('file_name', 'без имени')}]")
    if msg.get("photo") and not msg.get("caption"):
        parts.append("[фото без подписи]")
    return " ".join(parts).strip()


def format_digest(messages: list) -> str:
    if not messages:
        return "За последние сутки в чате «Лог проекта» новых сообщений не было."

    today_str = datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y")
    lines = [f"Лог проекта за {today_str} (сырые сообщения, без обработки):", ""]
    for author, ts, text in messages:
        lines.append(f"[{ts}] {author}: {text}")

    lines.append("")
    lines.append("— конец лога —")
    lines.append("Скопируй текст выше в чат с Claude и попроси оформить черновик "
                  "отчёта по структуре: Сделано / Решения / Риски и блокеры / Дальше.")
    return "\n".join(lines)


def send_message(chat_id: int, text: str):
    # Telegram ограничивает длину сообщения ~4096 символов — режем на части при необходимости
    max_len = 3800
    for i in range(0, len(text), max_len):
        chunk = text[i:i + max_len]
        resp = requests.post(
            f"{API_URL}/sendMessage",
            data={"chat_id": chat_id, "text": chunk},
            timeout=30,
        )
        resp.raise_for_status()


def main():
    offset = load_offset()
    updates = fetch_updates(offset)

    collected = []
    max_update_id = offset

    for upd in updates:
        max_update_id = max(max_update_id, upd["update_id"])
        msg = upd.get("message")
        if not msg:
            continue
        if msg.get("chat", {}).get("id") != LOG_CHAT_ID:
            continue

        text = extract_text(msg)
        if not text:
            continue

        author = msg.get("from", {}).get("first_name", "неизвестный")
        ts = datetime.fromtimestamp(msg["date"], tz=ZoneInfo(TIMEZONE)).strftime("%d.%m %H:%M")
        collected.append((author, ts, text))

    digest = format_digest(collected)
    send_message(REPORT_CHAT_ID, digest)
    save_offset(max_update_id)

    print(f"Обработано сообщений: {len(collected)}. Новый offset: {max_update_id}.")


if __name__ == "__main__":
    main()
