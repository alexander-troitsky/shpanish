"""Чтение словаря из Google-таблицы. Колонки по позиции: A=español, B=русский,
C=контекст (первая строка-заголовок пропускается).

Ключ сервисного аккаунта берётся:
  • из переменной окружения GOOGLE_CREDENTIALS_JSON (весь JSON строкой) — так на Railway;
  • иначе из файла GOOGLE_CREDENTIALS_FILE — так при локальном запуске.

Есть кэш в памяти: если сеть отвалилась, используем последнюю успешную загрузку.
"""
import json
import os

import gspread

import config

_cache = []


def _client():
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw:
        return gspread.service_account_from_dict(json.loads(raw))
    return gspread.service_account(filename=config.GOOGLE_CREDENTIALS_FILE)


def load_words():
    """Возвращает список dict {es, ru, ctx} в порядке таблицы, без дублей и пустых."""
    global _cache
    try:
        ws = _client().open_by_key(config.GSHEET_ID).sheet1
        values = ws.get_all_values()
    except Exception as e:  # сеть/доступ — отдаём кэш
        print(f"[sheets] не удалось загрузить таблицу: {e}; использую кэш ({len(_cache)})")
        return list(_cache)

    words, seen = [], set()
    for i, row in enumerate(values):
        if i == 0:  # строка заголовков
            continue
        es = (row[0] if len(row) > 0 else "").strip()
        ru = (row[1] if len(row) > 1 else "").strip()
        ctx = (row[2] if len(row) > 2 else "").strip()
        if not es or not ru or es in seen:
            continue
        seen.add(es)
        words.append({"es": es, "ru": ru, "ctx": ctx})

    _cache = words
    return list(words)
