* `app/core/bots/` — плоская куча `moving_bot_*.py` + `pricing_config.json` + `localities*.json`
* `app/core/handlers/moving_bot_handler.py` импортит эти модули напрямую
* `app/core/bots/__init__.py` регистрирует `moving_bot_v1` через `BotRegistry.register("moving_bot_v1", MOVING_BOT_CONFIG)`

---

# EPIC A1.1 — Bot Package Layout (moving_bot_v1 + example)

## Цель

1. Увести код moving_bot v1 в **отдельный пакет**: `app/core/bots/moving_bot_v1/`
2. Добавить **example** (шаблон) для будущих ботов
3. Сохранить обратную совместимость, чтобы ничего не “взорвать” сразу (особенно тесты и handler)

---

## Target Structure

```
app/core/bots/
  __init__.py
  moving_bot_v1/
    __init__.py
    config.py
    texts.py
    choices.py
    validators.py
    pricing.py
    geo.py
    localities.py
    data/
      localities.json
      localities_ru_aliases.auto.json
      localities_ru_aliases.collisions.json
      pricing_config.json

  example_bot/
    __init__.py
    config.py
    handler.py (optional, или только config как пример)
```

> Почему `data/`: чтобы JSON-файлы не были “сиротами” в корне и чтобы потом проще было паковать/доставать через `importlib.resources`.

---

## Step 1 — Move files (механически)

Перенести (с переименованием на более “пакетный” стиль):

* `moving_bot_config.py` → `moving_bot_v1/config.py`
* `moving_bot_texts.py` → `moving_bot_v1/texts.py`
* `moving_bot_choices.py` → `moving_bot_v1/choices.py`
* `moving_bot_validators.py` → `moving_bot_v1/validators.py`
* `moving_bot_pricing.py` → `moving_bot_v1/pricing.py`
* `moving_bot_geo.py` → `moving_bot_v1/geo.py`
* `moving_bot_localities.py` → `moving_bot_v1/localities.py`

Данные:

* `localities*.json` → `moving_bot_v1/data/`
* `pricing_config.json` → `moving_bot_v1/data/`

---

## Step 2 — Fix imports in handler (точечно)

В `app/core/handlers/moving_bot_handler.py` заменить импорты вида:

```py
from app.core.bots.moving_bot_config import MOVING_BOT_CONFIG
from app.core.bots.moving_bot_texts import get_text
...
```

на:

```py
from app.core.bots.moving_bot_v1.config import MOVING_BOT_CONFIG
from app.core.bots.moving_bot_v1.texts import get_text
from app.core.bots.moving_bot_v1.choices import ...
from app.core.bots.moving_bot_v1.validators import ...
from app.core.bots.moving_bot_v1.pricing import ...
from app.core.bots.moving_bot_v1.geo import ...
```

---

## Step 3 — Fix bots registry

Сейчас `app/core/bots/__init__.py` импортит плоские модули и регистрирует v1.

Меняем на:

```py
from app.core.bot_types import BotRegistry
from app.core.bots.moving_bot_v1.config import MOVING_BOT_CONFIG

BotRegistry.register("moving_bot_v1", MOVING_BOT_CONFIG)
```

И всё. В этом месте ты задаёшь “официальный” entrypoint для v1.

---

## Step 4 — Backward-compatible re-exports (чтобы ничего не сломалось внезапно)

Чтобы не чинить сразу весь проект/тесты/возможные импорты из других мест — оставь старые файлы **тонкими прокладками** на 1–2 релиза.

Например, `app/core/bots/moving_bot_config.py` становится:

```py
from app.core.bots.moving_bot_v1.config import *  # noqa
```

То же для остальных `moving_bot_*.py`.

**Плюс:**

* можно постепенно переехать
* диф минимальный
* откат лёгкий

**Минус:** временно дублируются файлы-обёртки (но это нормально для миграции).

---

## Step 5 — Перевести чтение JSON на package resources (или оставить относительные пути, но правильно)

### Вариант A (лучший и переносимый): `importlib.resources`

Если сейчас ты читаешь JSON через `Path(__file__).parent / "localities.json"`, то после переноса в `data/` меняется путь, и это ломается при упаковке.

Рекомендую сделать маленькую утилиту внутри `moving_bot_v1/data_loader.py`:

* `load_json("localities.json")` → достаёт из `moving_bot_v1/data/`

Это снизит будущую боль.

### Вариант B (быстро): оставить Path, но обновить путь на `data/`

Если сейчас у тебя простой runtime на файловой системе и не собираешь в wheel — это ок как MVP.

---

## Step 6 — Add `example_bot/` (как референс для будущих движков)

Минимум:

* `example_bot/config.py` с простым BotConfig
* `example_bot/__init__.py` чтобы было понятно “как устроено”
* Не регистрировать его по умолчанию (только как пример)

Или вообще сделать `app/core/bots/_template/` чтобы никто случайно не активировал.

---

## Step 7 — Tests / Done Criteria

**DoD (минимальный):**

* все существующие тесты зелёные
* `moving_bot_v1` работает как раньше
* `BotRegistry` регистрирует `moving_bot_v1` из нового пакета
* JSON/справочники читаются корректно

**Нужно прогнать:**

* unit tests (у тебя их много — это идеально)
* smoke: 1–2 типовых сценария диалога

---

# Результат, который ты получишь

1. `app/core/bots` становится **каталогом движков**, а не свалкой файлов
2. Новый бот добавляется так:

   * создал папку `app/core/bots/<new_bot>/...`
   * добавил регистрацию в одном месте (registry/или `bots/__init__.py`)
3. Импорты становятся предсказуемыми
4. Меньше шансов “случайно зацепить” v1 при работе над v2

---

# Как это увязать с твоим текущим `enabled_bots` / `worker_role`

То, что ты добавил в `Settings` (`enabled_bots`, `worker_role`) — это как раз фундамент EPIC A и оно не конфликтует с A1.1.
Наоборот: после переноса ботов в папки **lazy import становится чище**, потому что ты можешь импортить ровно `app.core.bots.moving_bot_v1` как пакет, и внутри него уже всё локально.

---
