# Moving Bot v2 (LLM) — Incremental Implementation Plan

**Project:** Stage0 Bot
**Scope:** новая версия moving-бота для улучшенного сбора заявки через LLM, без дестабилизации текущего сценарного moving_bot (v1).
**Principles:**

* `moving_bot` (v1) остаётся рабочим и “не трогаем” за пределами минимального фундамента под dispatch (как в Dispatch plan). 
* `moving_bot_v2` развиваем итерациями, с возможностью отката на v1 per-tenant.
* LLM **не принимает бизнес-решений** (pricing/валидаторы/сбор лида — всё в Lead Core).
* LLM используется как **parser + gap detector + question generator** в рамках строгих ограничений.

---

## 1. Цели и не-цели

### 1.1 Цели

* Собрать заявку в “наилучшем виде”: структурированные поля + минимальный набор уточнений.
* Уметь переваривать “кашу” в одном сообщении (свободный текст, смесь языков, пропущенные поля).
* Сохранять совместимость с существующим Lead Core/валидаторами/прайсингом.

### 1.2 Не-цели

* Не переносить расчёт цены в LLM.
* Не заменять существующие валидаторы LLM-логикой.
* Не делать “полу-чатбота с фантазией”: ответы только по schema и по правилам.

---

## 2. Архитектура и разделение ответственности

### 2.1 Lead Core (Stable)

Отвечает за:

* state machine/сессии
* нормализацию (если уже есть)
* валидаторы
* pricing estimate
* создание Lead
* нотификации оператору

**Lead Core не знает, LLM-бот это или сценарный бот.** Он принимает одинаковые нормализованные поля.

### 2.2 Moving Bot v2 (New handler)

Отвечает за:

* извлечение и нормализацию полей через LLM
* определение `missing_fields`
* генерацию *разрешённых* уточняющих вопросов
* формирование `LeadDraft/SessionState.data` так, как ожидает текущий движок

### 2.3 Dispatch Layer (New isolated)

Работает по событию `LeadFinalized` и отдельной модели `CrewLeadView`. 
`moving_bot_v2` только доводит лид до finalized тем же способом, что и v1.

---

## 3. Стратегия внедрения без поломок

### 3.1 Два тенанта (рекомендовано)

* `tenant=moving_prod_v1` → текущий `moving_bot_handler.py`
* `tenant=moving_llm_v2` → новый `moving_bot_v2_handler.py`

Можно повесить на отдельный номер/канал. Это снижает риск и упрощает A/B.

### 3.2 Фичефлаги (если захочешь внутри одного tenant)

* `bots.moving.version = "v1" | "v2_llm"`
* `bots.moving.llm.enabled = true/false`
* `bots.moving.llm.mode = "fallback_parser" | "full_dialog"`

---

## 4. Изменения в структуре проекта (фундамент)

Проект уже имеет `app/core/handlers/moving_bot_handler.py` и engine-слой. (См. текущую структуру в app.zip.)

### 4.1 Новые модули (предложение)

Создать:

```
app/core/agents/
  __init__.py
  llm_client.py
  llm_models.py
  llm_schemas.py
  prompt_registry.py
  prompt_templates/
    moving_v2_extract_v1.txt
    moving_v2_question_v1.txt
  guardrails.py
  conversation_store.py
```

И новый handler:

```
app/core/handlers/moving_bot_v2_handler.py
app/core/bots/moving_bot_v2_config.py
app/core/bots/moving_bot_v2_texts.py   (если нужно отдельно)
```

### 4.2 Почему отдельная папка agents

Чтобы потом туда же расширять “диспетчерские агенты”, но не смешивать с Lead Core.

---

## 5. Контракт LLM: строгое structured output (JSON schema)

### 5.1 Ключевое правило

**LLM всегда возвращает JSON**, который валидируется Pydantic-схемой.
Если невалидно → “safe fallback” (переспрашиваем/переводим на оператора/уходим в v1-step).

### 5.2 Pydantic schema (логическая)

`MovingLeadExtract`:

* `language`: `"ru" | "en" | "he" | "unknown"`
* `fields`:

  * `from_locality` (ключ справочника) / `from_text` (сырой fallback)
  * `to_locality` / `to_text`
  * `date_iso` (YYYY-MM-DD)
  * `time_window` (`"morning"|"day"|"evening"|"exact"` + `exact_time` optional)
  * `volume_category` (enum из VOLUME_CHOICES_DICT)
  * `pickup_count` (1..3)
  * `floors`: список по pickup + destination (floor_num, elevator_bool)
  * `extras`: нормализованный список из `EXTRA_OPTIONS`
  * `items`: список item-лейблов (fridge, washer, sofa, etc.)
  * `notes_safe`: только безопасные заметки без PII (опционально)
* `missing_fields`: список enum-ключей (см. 5.3)
* `next_question`:

  * `field`: missing_field key
  * `text`: строка (один вопрос)
  * `choices`: optional (кнопки/варианты)

### 5.3 Missing fields enum (минимальный набор)

* `from_locality`
* `to_locality`
* `date`
* `time_window`
* `volume_category`
* `floors_from`
* `floors_to`
* `extras_or_items` (если нужно)
* `pickup_count` (если multi-pickup включён)

---

## 6. Guardrails и политика вопросов

### 6.1 Политика “один ход — один вопрос”

* LLM может задать **только один** вопрос за сообщение.
* Максимум уточнений: `N=4` (конфиг).
* Если после N всё ещё дырки → создаём черновик + оператору сигнал “needs_manual_followup”.

### 6.2 Вопросы только из allowlist

`missing_field → question_template + choices`

Примеры:

* `date` → “На какую дату нужен переезд?” + кнопки (tomorrow/2-3 days/this week/specific)
* `volume_category` → кнопки из твоего `VOLUME_CHOICES_DICT`
* `time_window` → кнопки `TIME_SLOT_CHOICES_DICT`
* `floors_*` → “Какой этаж и есть ли лифт?” (шаблонный формат)

LLM **не должен**:

* просить телефон/имя (это уже есть в канале)
* просить точный адрес в Crew-ветке (это про dispatch privacy, см. ниже) 

---

## 7. Состояние диалога (Conversation state)

### 7.1 Что хранить

В `SessionState.data.custom` (по аналогии с текущим handler) можно хранить:

* `llm_v2.enabled: bool`
* `llm_v2.turns: int`
* `llm_v2.last_extract: dict` (sanitized)
* `llm_v2.missing_fields: []`
* `llm_v2.pending_field: str`

### 7.2 Где хранить

* На старте достаточно текущего session storage (как у тебя сейчас).
* Потом можно вынести в Redis (но это не блокер).

---

## 8. Алгоритм v2 (основной цикл)

### 8.1 On message

1. Принять `user_text`/attachments.
2. Если step “button-only” и пришёл button — обработать как в v1.
3. Иначе вызвать `extract()` в LLM:

   * передать “known context” из session (уже собранные поля)
   * передать правила/choices enums (строго)
4. Провалидировать JSON по schema.
5. Применить extracted поля в session:

   * нормализация: locality → ключи справочника (или оставить text и пометить missing)
   * volume/time/date → твои enums/форматы
6. Если `missing_fields` не пуст:

   * выбрать приоритетное поле
   * отправить `next_question` (кнопки если есть)
7. Иначе:

   * перейти к вычислению estimate/confirm как в v1 (используя существующие функции).

### 8.2 Приоритет missing_fields

Пример:

1. route (from/to)
2. date
3. time_window
4. volume
5. floors
6. extras/items

---

## 9. Совместимость с Dispatch privacy model

Твой Dispatch план требует **CrewLeadView allowlist**, а не “чистку текста”. 
Значит в v2:

* Все “сырые” тексты от пользователя хранятся только в FullLead (PII зона).
* CrewLeadView строится только из нормализованных полей (route/date/time/volume/floors/items/estimate).
* LLM `notes_safe` допускается только если там гарантированно нет PII (лучше на MVP вообще выключить).

---

## 10. Набор итераций (roadmap)

### Iteration 0 — Skeleton + Feature Flag

**Цель:** добавить пустой `moving_bot_v2_handler.py`, включаемый только для `tenant=moving_llm_v2`.
**Done criteria:**

* handler подключён в registry
* smoke: приветствие, базовая сессия, логирование

### Iteration 1 — Fallback Parser Mode

**Цель:** LLM вызывается только когда free-text не проходит валидаторы/парсеры v1 (или пользователь пишет “всё в одном сообщении”).
**Done criteria:**

* LLM корректно извлекает route/date/volume хотя бы из 70% “каши”
* при неудаче — безопасный фолбек в v1-диалог

### Iteration 2 — Full LLM Dialog (1 question per turn)

**Цель:** LLM ведёт уточнения по missing_fields (строго по allowlist).
**Done criteria:**

* N уточнений ограничен
* стабильная сборка лида без “болтовни”

### Iteration 3 — Multi-pickup + Floors normalization

**Цель:** v2 корректно поддерживает pickups 1–3 и floors по всем точкам (с учётом твоей текущей логики multi-pickup).
**Done criteria:**

* LLM-extract умеет заполнять `pickup_count` и floors массив

### Iteration 4 — Tight integration with LeadFinalized + Dispatch workflows

**Цель:** когда lead finalized — dispatch слой получает стандартное событие и может делать operator fallback/crew publish, не завися от версии бота. 
**Done criteria:**

* никаких изменений в dispatch из-за v2

---

## 11. Observability, безопасность, стоимость

### 11.1 Логи

* correlation_id на сессию/лид
* логировать токены/latency/ошибки
* **не логировать сырой пользовательский текст**, или логировать только redacted

### 11.2 Rate limiting

* лимит LLM calls per session
* circuit breaker на провайдера (timeout → fallback)

### 11.3 Idempotency

* если пользователь повторил сообщение/кнопку → не плодить LLM calls

---

## 12. Деплой и независимость диспетчерской

Рекомендуемая стратегия (на сейчас):

* один репо
* один docker-compose
* два профиля:

`core`:

* api + worker + postgres (+redis)

`dispatch`:

* dispatch-worker/service (может быть тот же воркер, но отдельный entrypoint)

`llm_v2`:

* (обычно не отдельный сервис, просто новый handler внутри api/worker)

Если захочешь прям “отдельно деплоить движки ботов” — это следующий этап, но MVP проще держать в одном деплое и включать per-tenant.

---

# Приложение A — минимальные изменения в v1 (то, что ты хотел)

Только то, что совпадает с Iteration 1 Dispatch plan: “Operator fallback (manual copy)”. 
Т.е. v1 получает:

* генерацию `CrewLeadView`
* job `notify_operator_crew_fallback` на `LeadFinalized`
* конфиг `dispatch.operator.send_crew_fallback=true`

Больше ничего.

---

# Приложение B — критерии “можно включать на прод”

* 50–100 реальных диалогов на v2 tenant без критических фейлов
* доля “operator manual followup” не выше X% (например 15–25%)
* среднее количество уточнений ≤ 3
* нет утечек PII в crew-флоу

