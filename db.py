"""Хранилище состояния (SQLite). В БД попадают только слова, дошедшие до лесенки
(in_ladder) или выученные (graduated). «Новые» слова живут в Google-таблице и
считаются доступными, пока не появились здесь."""
import sqlite3
from datetime import date, timedelta

import config

_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db():
    c = conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards (
            es TEXT PRIMARY KEY,
            ru TEXT,
            ctx TEXT,
            status TEXT,            -- 'in_ladder' | 'graduated'
            step INTEGER,
            next_review TEXT,       -- ISO-дата
            introduced_at TEXT,
            graduated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            es TEXT,
            kind TEXT,              -- 'introduced' | 'review' | 'graduated'
            grade TEXT              -- 'know' | 'dont' | NULL
        );
        CREATE TABLE IF NOT EXISTS daily (
            day TEXT PRIMARY KEY,
            new_introduced INTEGER DEFAULT 0,
            active_seconds INTEGER DEFAULT 0,
            quota_done INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    c.commit()


# ---- meta ----
def set_meta(key, value):
    c = conn()
    c.execute("INSERT INTO meta(key,value) VALUES(?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    c.commit()


def get_meta(key, default=None):
    row = conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ---- cards ----
def known_es() -> set:
    rows = conn().execute("SELECT es FROM cards").fetchall()
    return {r["es"] for r in rows}


def get_card(es):
    return conn().execute("SELECT * FROM cards WHERE es=?", (es,)).fetchone()


def add_to_ladder(word, today_iso, now_iso):
    """word: dict с ключами es, ru, ctx. Ступень 1, повтор через 1 день."""
    nr = (date.fromisoformat(today_iso) + timedelta(days=config.STEP_INTERVALS[1])).isoformat()
    c = conn()
    c.execute(
        "INSERT INTO cards(es,ru,ctx,status,step,next_review,introduced_at,graduated_at) "
        "VALUES(?,?,?, 'in_ladder', 1, ?, ?, NULL) "
        "ON CONFLICT(es) DO UPDATE SET status='in_ladder', step=1, next_review=excluded.next_review",
        (word["es"], word["ru"], word.get("ctx", ""), nr, now_iso),
    )
    c.execute("INSERT INTO events(ts,es,kind,grade) VALUES(?,?, 'introduced', NULL)", (now_iso, word["es"]))
    c.commit()


def set_step(es, step, today_iso):
    nr = (date.fromisoformat(today_iso) + timedelta(days=config.STEP_INTERVALS[step])).isoformat()
    c = conn()
    c.execute("UPDATE cards SET step=?, next_review=? WHERE es=?", (step, nr, es))
    c.commit()


def graduate(es, now_iso):
    c = conn()
    c.execute("UPDATE cards SET status='graduated', next_review=NULL, graduated_at=? WHERE es=?",
              (now_iso, es))
    c.commit()


def log_review(es, knows, now_iso):
    conn().execute("INSERT INTO events(ts,es,kind,grade) VALUES(?,?, 'review', ?)",
                   (now_iso, es, "know" if knows else "dont"))
    conn().commit()


def due_cards(today_iso):
    rows = conn().execute(
        "SELECT * FROM cards WHERE status='in_ladder' AND next_review<=?", (today_iso,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---- daily ----
def _ensure_day(day):
    conn().execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
    conn().commit()


def inc_new_introduced(day, n):
    _ensure_day(day)
    conn().execute("UPDATE daily SET new_introduced=new_introduced+? WHERE day=?", (n, day))
    conn().commit()


def get_new_introduced(day):
    _ensure_day(day)
    return conn().execute("SELECT new_introduced FROM daily WHERE day=?", (day,)).fetchone()[0]


def add_active_seconds(day, secs):
    _ensure_day(day)
    conn().execute("UPDATE daily SET active_seconds=active_seconds+? WHERE day=?", (int(secs), day))
    conn().commit()


def set_quota_done(day, done=True):
    _ensure_day(day)
    conn().execute("UPDATE daily SET quota_done=? WHERE day=?", (1 if done else 0, day))
    conn().commit()


def is_quota_done(day):
    _ensure_day(day)
    return bool(conn().execute("SELECT quota_done FROM daily WHERE day=?", (day,)).fetchone()[0])


# ---- stats ----
def counts_by_step():
    rows = conn().execute(
        "SELECT step, COUNT(*) c FROM cards WHERE status='in_ladder' GROUP BY step"
    ).fetchall()
    return {r["step"]: r["c"] for r in rows}


def graduated_count():
    return conn().execute("SELECT COUNT(*) FROM cards WHERE status='graduated'").fetchone()[0]


def graduated_since(iso_dt):
    rows = conn().execute(
        "SELECT es FROM cards WHERE status='graduated' AND graduated_at>=? ORDER BY graduated_at",
        (iso_dt,)
    ).fetchall()
    return [r["es"] for r in rows]


def active_seconds_since(day_from):
    row = conn().execute(
        "SELECT COALESCE(SUM(active_seconds),0) s FROM daily WHERE day>=?", (day_from,)
    ).fetchone()
    return row["s"]
