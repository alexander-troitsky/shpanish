"""Учебная логика.

Лесенка: «помню» поднимает на ступень выше (на последней — выпуск), «не помню»
опускает на одну ступень вниз (минимум — ступень 1).

Сессия:
  1) Новые слова: подпартии по SUBBATCH. Каждая проходит ДВЕ фазы —
     ES→RU, затем RU→ES. В каждой фазе PASSES прогонов; кнопки «помню/не помню»
     только на последнем прогоне. «Не помню» в сессии => слово крутится, пока
     не дашь «помню». Пройдя обе фазы, слово входит в лесенку (ступень 1).
  2) Повторения: слова со сроком <= сегодня, направление всегда RU→ES,
     один показ + оценка.
"""
import config
import db


# ---------- лесенка ----------
def apply_ladder(es: str, knows: bool):
    card = db.get_card(es)
    if card is None:
        return
    step = card["step"]
    today = config.today_str()
    now_iso = config.now().isoformat()
    db.log_review(es, knows, now_iso)
    if knows:
        if step >= config.MAX_STEP:
            db.graduate(es, now_iso)
            conn_event(es, "graduated", now_iso)
        else:
            db.set_step(es, step + 1, today)
    else:
        db.set_step(es, max(1, step - 1), today)


def conn_event(es, kind, now_iso):
    db.conn().execute("INSERT INTO events(ts,es,kind,grade) VALUES(?,?,?,NULL)", (now_iso, es, kind))
    db.conn().commit()


# ---------- сессия ----------
class Session:
    def __init__(self, new_pool, new_quota, review_queue):
        self.new_pool = list(new_pool)          # доступные новые слова (dict es/ru/ctx)
        self.new_quota = max(0, new_quota)      # сколько новых ввести в этом прогоне
        self.review_queue = list(review_queue)  # слова к повторению (dict)
        self.review_lapsed = set()  # es слов, которым лапс (-1 ступень) уже засчитан в этой сессии

        self.stage = "new"          # 'new' | 'review' | 'done'
        self.direction = "es_ru"    # фаза A / фаза B
        self.batch = []             # текущая подпартия (<= SUBBATCH)
        self.pass_num = 1
        self.queue = []             # слова, оставшиеся в текущем прогоне
        self.redo = []              # «не помню» на последнем прогоне -> повторить
        self.current = None         # текущее слово (dict)
        self.gradable = False       # показывать ли «помню/не помню»
        self.answer_shown = False

        self.introduced_this_session = 0  # для счётчика дневной нормы

        if self.new_quota > 0 and self.new_pool:
            self._start_subbatch()
        else:
            self.stage = "review"

    # --- управление новой подпартией ---
    def _start_subbatch(self):
        take = min(config.SUBBATCH, self.new_quota, len(self.new_pool))
        self.batch = [self.new_pool.pop(0) for _ in range(take)]
        self.direction = "es_ru"
        self.pass_num = 1
        self.queue = list(self.batch)
        self.redo = []

    def _commit_batch(self):
        today = config.today_str()
        now_iso = config.now().isoformat()
        for w in self.batch:
            db.add_to_ladder(w, today, now_iso)
        db.inc_new_introduced(today, len(self.batch))
        self.introduced_this_session += len(self.batch)
        self.new_quota -= len(self.batch)
        self.batch = []

    # --- шаги ---
    def next_step(self) -> dict:
        """Возвращает, что показать дальше:
        {'kind':'card', 'word':..., 'direction':..., 'gradable':bool} |
        {'kind':'more_new_prompt', 'reviews_due':int} |
        {'kind':'finished'}"""
        if self.stage == "new":
            return self._step_new()
        if self.stage == "review":
            return self._step_review()
        return {"kind": "finished"}

    def _step_new(self) -> dict:
        while True:
            if self.queue:
                self.current = self.queue.pop(0)
                self.gradable = (self.pass_num == config.PASSES)
                self.answer_shown = False
                return {"kind": "card", "word": self.current,
                        "direction": self.direction, "gradable": self.gradable}
            # прогон закончился
            if self.pass_num < config.PASSES:
                self.pass_num += 1
                self.queue = list(self.batch)
                continue
            # последний прогон: добиваем «не помню»
            if self.redo:
                self.queue = self.redo
                self.redo = []
                continue
            # фаза закончена
            if self.direction == "es_ru":
                self.direction = "ru_es"
                self.pass_num = 1
                self.queue = list(self.batch)
                self.redo = []
                continue
            # обе фазы пройдены -> в лесенку
            self._commit_batch()
            if self.new_quota > 0 and self.new_pool:
                self._start_subbatch()
                continue
            # новые на этот прогон закончились
            self.stage = "review"
            if self.new_pool:  # есть ещё новые в запасе — спросим
                return {"kind": "more_new_prompt", "reviews_due": len(self.review_queue)}
            return self._step_review()

    def _step_review(self) -> dict:
        if self.review_queue:
            self.current = self.review_queue.pop(0)
            self.gradable = True
            self.answer_shown = False
            return {"kind": "card", "word": self.current, "direction": "ru_es", "gradable": True}
        self.stage = "done"
        return {"kind": "finished"}

    # --- реакции пользователя ---
    def reveal(self):
        self.answer_shown = True

    def grade(self, knows: bool) -> dict:
        if self.stage == "new":
            if not knows and self.current is not None:
                self.redo.append(self.current)  # вернётся в этой же сессии
            return self._step_new()
        if self.stage == "review":
            es = self.current["es"] if self.current else None
            if es is not None:
                if knows:
                    # первое «помню» — двигаем по лесенке как обычно;
                    # «помню» после лапса в этой сессии — слово просто дотянуто, лесенку не трогаем
                    if es not in self.review_lapsed:
                        apply_ladder(es, True)
                else:
                    # «не помню»: лапс (-1 ступень) засчитываем один раз за сессию,
                    # дальше слово крутится в этой же сессии, пока не дашь «помню»
                    if es not in self.review_lapsed:
                        apply_ladder(es, False)
                        self.review_lapsed.add(es)
                    self.review_queue.append(self.current)  # вернуть позже в этой сессии
            return self._step_review()
        return {"kind": "finished"}

    def add_new(self, n=config.DAILY_NEW) -> dict:
        self.new_quota += n
        if self.new_pool:
            self.stage = "new"
            self._start_subbatch()
            return self._step_new()
        return self._step_review() if self.review_queue else {"kind": "finished"}
