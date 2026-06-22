"""Конфигурация бота. Значения берутся из переменных окружения (.env)."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GSHEET_ID = os.getenv("GSHEET_ID", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

DB_PATH = os.getenv("DB_PATH", "vocab.db")

TZ = ZoneInfo(os.getenv("TZ", "Europe/Madrid"))

# Напоминания: каждый час с REMINDER_START до REMINDER_END включительно.
REMINDER_START = int(os.getenv("REMINDER_START", "10"))
REMINDER_END = int(os.getenv("REMINDER_END", "18"))

# Сколько новых слов вводить за день по умолчанию (кнопка «Ещё новые» добавляет ещё столько же).
DAILY_NEW = int(os.getenv("DAILY_NEW", "10"))

# Размер подпартии внутри сессии заучивания новых слов.
SUBBATCH = int(os.getenv("SUBBATCH", "5"))

# Число прогонов по подпартии в каждой фазе.
PASSES = int(os.getenv("PASSES", "3"))

# Лесенка интервального повторения: ступень -> дней до следующего повторения.
STEP_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}
MAX_STEP = max(STEP_INTERVALS)

# Порог простоя (сек): паузы дольше не засчитываются во «время занятий».
IDLE_CAP_SECONDS = 120


def now() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now().date().isoformat()
