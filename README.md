# Бот интервального повторения испанских слов

Telegram-бот: учит испанские слова карточками по методу интервального повторения.
Словарь живёт в Google-таблице, прогресс — в локальной SQLite. ИИ при работе не
используется (платить только за сервер).

## Как это работает

**Новые слова** подаются подпартиями по 5. Каждая проходит две фазы:
1. **ES→RU** (узнавание): 3 прогона, кнопки «Помню/Не помню» — только на 3-м.
2. **RU→ES** (воспроизведение): то же самое.

«Не помню» на 3-м прогоне → слово крутится в этой же сессии, пока не дашь «Помню».
Пройдя обе фазы, слово входит в **лесенку**: повтор через 1 → 3 → 7 → 16 → 35 дней.
На каждом повторении (всегда RU→ES, один показ): «Помню» — на ступень выше, «Не
помню» — на ступень вниз. «Помню» на 5-й ступени → слово **выучено** и больше не
показывается.

За день вводится 10 новых, дальше идут повторения. Кнопка «Ещё новые» добавляет
ещё десятку. Напоминания — раз в час с 10:00 до 18:00 (Барселона), гаснут, как
только дневная норма пройдена.

**Команды:** `/review` — занятие сейчас · `/stats` — статистика · `/stop` — прервать.

## Настройка

### 1. Токен бота
В Telegram у **@BotFather**: `/newbot` → получишь `BOT_TOKEN`.

### 2. Доступ к Google-таблице (бесплатно)
1. https://console.cloud.google.com → создать проект.
2. **APIs & Services → Library → Google Sheets API → Enable.**
3. **APIs & Services → Credentials → Create credentials → Service account.**
4. У созданного аккаунта: **Keys → Add key → JSON** → скачать. Положить рядом с
   ботом как `credentials.json`.
5. Скопировать e-mail сервисного аккаунта (вида `...@...iam.gserviceaccount.com`)
   и **поделиться** с ним своей таблицей (кнопка «Поделиться», доступ «Читатель»).

Таблица: колонки **A = español, B = русский, C = контекст**, первая строка —
заголовки. Ровно тот формат, что отдаёт Claude при разборе чата с урока.

### 3. Запуск
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # заполнить BOT_TOKEN и GSHEET_ID
python bot.py
```
`GSHEET_ID` — это часть URL таблицы: `docs.google.com/spreadsheets/d/<ВОТ_ЭТО>/edit`.
В Telegram отправь боту `/start`.

### 4. Деплой на Railway (рекомендуется)

Railway держит процесс живым сам — ни SSH, ни systemd не нужны. Без терминала:

1. **GitHub:** создай репозиторий и загрузи туда файлы проекта (через веб-интерфейс
   GitHub: «Add file → Upload files»). `.env` и `credentials.json` НЕ загружай —
   их заменяют переменные окружения. Файл `.gitignore` уже их исключает.
2. **Railway → New Project → Deploy from GitHub repo** → выбери репозиторий.
   Старт-команда (`python bot.py`) и автоперезапуск берутся из `railway.json`.
3. **Volume** (чтобы база не стиралась при передеплое): в проекте ⌘K → *New Volume*,
   примонтировать к сервису на путь **`/data`**.
4. **Variables** (вкладка переменных сервиса) — добавь:
   - `BOT_TOKEN` — токен бота
   - `GSHEET_ID` — ID таблицы
   - `GOOGLE_CREDENTIALS_JSON` — открой скачанный `credentials.json` и вставь его
     содержимое целиком как значение
   - `DB_PATH` = `/data/vocab.db`
   - `TZ` = `Europe/Madrid`
   - `RAILWAY_RUN_UID` = `0`  *(обязательно: Volume монтируется под root)*
5. Дождись деплоя, в Telegram отправь боту `/start`.

Этот бот работает на long-polling — порт открывать не нужно, «no exposed port» это норма.
При передеплое сервиса с Volume бывает несколько секунд простоя — для личного бота
неважно.

> Альтернатива без GitHub — Railway CLI: `npm i -g @railway/cli`, затем из папки
> проекта `railway init` и `railway up`. Volume и Variables настраиваются так же.

### 5. Деплой на VPS (systemd)
`/etc/systemd/system/esbot.service`:
```ini
[Unit]
Description=Spanish vocab bot
After=network.target

[Service]
WorkingDirectory=/opt/esbot
ExecStart=/opt/esbot/venv/bin/python /opt/esbot/bot.py
Restart=always
User=esbot

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now esbot
journalctl -u esbot -f      # логи
```

## Пополнение словаря
Новый дамп из Zoom → Claude в чат → получаешь готовый CSV → импортируешь/дописываешь
строки в Google-таблицу. Бот подхватит новые слова при следующем занятии.

## Файлы
- `bot.py` — Telegram-интерфейс, напоминания, статистика
- `srs.py` — лесенка и конечный автомат сессии
- `db.py` — SQLite (карточки, события, дневная статистика)
- `sheets.py` — чтение словаря из Google Sheets
- `config.py` — настройки (интервалы, расписание, часовой пояс)

## Заметки
- Состояние активной сессии — в памяти: если бот перезапустить посреди занятия,
  начни заново через `/review` (прогресс по выученным словам не теряется).
- Интервалы лесенки и окно напоминаний меняются в `.env` / `config.py`.
