# Universal Engine Guide

## Overview

The Bridgley platform now supports **multiple bot types** through a universal engine architecture. Each tenant can use a different bot type (moving bot, restaurant bot, etc.) without changing the core infrastructure.

## Architecture

### Key Components

1. **Universal Domain Models** (`app/core/domain.py`)
   - `SessionState` - Universal session state with flexible `step` (string) and `bot_type` fields
   - `LeadData` - Flexible data container with both predefined fields and `custom` dict
   - `Step` - Base enum with common steps (WELCOME, DONE)

2. **Bot Handler Protocol** (`app/core/bot_handler.py`)
   - Defines interface that all bot handlers must implement
   - `BotHandler` protocol with methods: `new_session()`, `handle_text()`, `handle_media()`, `get_payload()`
   - `BotHandlerRegistry` - Central registry for all bot handlers

3. **Universal Engine** (`app/core/universal_engine.py`)
   - Bot-agnostic conversation engine
   - Delegates to appropriate `BotHandler` based on `bot_type`
   - Static methods: `new_session()`, `handle_text()`, `handle_media()`, `get_payload()`

4. **Bot Handlers** (`app/core/handlers/`)
   - Each bot type has its own handler implementation
   - `MovingBotHandler` - Implements moving/delivery bot logic (refactored from `engine.py`)
   - Future: `RestaurantBotHandler`, `HotelBotHandler`, etc.

## How It Works

### 1. Bot Handler Registration

Bot handlers are registered at import time:

```python
# app/core/handlers/__init__.py
from app.core.bot_handler import BotHandlerRegistry
from app.core.handlers.moving_bot_handler import MovingBotHandler

BotHandlerRegistry.register("moving_bot_v1", MovingBotHandler())
```

### 2. Creating a Session

```python
from app.core.universal_engine import UniversalEngine

# Create session for specific bot type
session = UniversalEngine.new_session(
    tenant_id="tenant_01",
    chat_id="+1234567890",
    bot_type="moving_bot_v1",  # Specify bot type
    language="ru"
)
```

### 3. Processing Messages

```python
# The universal engine routes to the correct bot handler
new_state, reply, is_done = UniversalEngine.handle_text(session, "Hello")
```

### 4. Using in Stage0Engine

```python
# app/core/use_cases.py
engine = Stage0Engine(
    tenant_id="tenant_01",
    provider="twilio",
    sessions=session_store,
    leads=lead_repo,
    inbound=inbound_repo,
    bot_type="moving_bot_v1"  # Configure bot type per engine
)
```

## Creating a New Bot Type

### Step 1: Define Bot Configuration

Create `app/core/bots/your_bot_config.py`:

```python
from enum import Enum
from app.core.bot_types import BotConfig, Intent, IntentPatterns, Translation

class YourBotStep(str, Enum):
    WELCOME = "welcome"
    STEP1 = "step1"
    STEP2 = "step2"
    DONE = "done"

YOUR_BOT_CONFIG = BotConfig(
    bot_id="your_bot_v1",
    name=Translation(ru="Ваш бот", en="Your Bot", he="הבוט שלך"),
    description=Translation(ru="Описание", en="Description", he="תיאור"),
    step_enum=YourBotStep,
    initial_step=YourBotStep.WELCOME.value,
    final_step=YourBotStep.DONE.value,
    intent_patterns={...},
    translations={...},
    choices={...},
    choice_labels={...},
)
```

### Step 2: Create Bot Handler

Create `app/core/handlers/your_bot_handler.py`:

```python
from app.core.domain import SessionState
from app.core.bot_handler import BotHandler
from app.core.bots.your_bot_config import YOUR_BOT_CONFIG
import uuid

class YourBotHandler:
    def __init__(self):
        self._config = YOUR_BOT_CONFIG

    @property
    def config(self):
        return self._config

    def new_session(self, tenant_id: str, chat_id: str, language: str = "ru") -> SessionState:
        lead_id = uuid.uuid4().hex[:12]
        return SessionState(
            tenant_id=tenant_id,
            chat_id=chat_id,
            lead_id=lead_id,
            bot_type="your_bot_v1",
            step="welcome",
            language=language
        )

    def handle_text(self, state: SessionState, text: str):
        # Implement your bot's conversation logic
        # Return (new_state, reply, is_done)
        ...

    def handle_media(self, state: SessionState):
        # Implement media handling
        # Return (new_state, optional_reply)
        ...

    def get_payload(self, state: SessionState) -> dict:
        # Generate final lead payload
        return {
            "tenant_id": state.tenant_id,
            "lead_id": state.lead_id,
            "bot_type": state.bot_type,
            "step": state.step,
            "data": {...},
        }
```

### Step 3: Register Handler

Add to `app/core/handlers/__init__.py`:

```python
from app.core.handlers.your_bot_handler import YourBotHandler

BotHandlerRegistry.register("your_bot_v1", YourBotHandler())
```

### Step 4: Use Your Bot

```python
engine = Stage0Engine(
    tenant_id="tenant_01",
    provider="twilio",
    sessions=sessions,
    leads=leads,
    inbound=inbound,
    bot_type="your_bot_v1"  # Use your new bot type!
)
```

## Benefits

### 1. Multi-Tenancy
Each tenant can use a different bot type:
```python
# Tenant A uses moving bot
engine_a = Stage0Engine(..., bot_type="moving_bot_v1")

# Tenant B uses restaurant bot
engine_b = Stage0Engine(..., bot_type="restaurant_bot_v1")
```

### 2. Easy Testing
Test different bot types independently:
```python
def test_moving_bot():
    handler = BotHandlerRegistry.get("moving_bot_v1")
    session = handler.new_session("t1", "c1")
    new_state, reply, done = handler.handle_text(session, "Hello")
    assert reply == "..."
```

### 3. No Infrastructure Changes
- Same database schema (sessions, leads, inbound_messages)
- Same repositories and ports
- Same HTTP endpoints
- Just different conversation flows!

### 4. Type Safety
The `BotHandler` protocol ensures all handlers implement the required interface.

## Data Storage

### Session State
```python
SessionState(
    tenant_id="t1",
    chat_id="c1",
    lead_id="abc123",
    bot_type="moving_bot_v1",  # Identifies which bot handler to use
    step="cargo",               # Current step (bot-specific)
    language="ru",
    data=LeadData(...),
    metadata={...}              # Bot-specific extra data
)
```

### Lead Data
```python
# Moving bot uses predefined fields
state.data.cargo_description = "Furniture"
state.data.addresses = "NYC to Boston"

# New bots can use custom dict
state.data.custom["cuisine"] = "italian"
state.data.custom["party_size"] = 4
```

## Migration from Old Engine

### Old Code (engine.py)
```python
from app.core.engine import handle_text, new_session

session = new_session(tenant_id, chat_id)
new_state, reply, done = handle_text(session, text)
```

### New Code (universal_engine.py)
```python
from app.core.universal_engine import UniversalEngine

session = UniversalEngine.new_session(tenant_id, chat_id, "moving_bot_v1")
new_state, reply, done = UniversalEngine.handle_text(session, text)
```

The old `engine.py` is kept for backward compatibility but is no longer recommended.

## Current Bot Types

| Bot ID | Description | Status |
|--------|-------------|--------|
| `moving_bot_v1` | Moving/delivery service bot | ✅ Active |
| `restaurant_bot_v1` | Restaurant reservation bot | 📋 Example config available |

## File Structure

```
app/core/
├── domain.py                    # Universal domain models
├── bot_types.py                 # BotConfig, Translation, Intent
├── bot_handler.py               # BotHandler protocol & registry
├── universal_engine.py          # Universal conversation engine
├── use_cases.py                 # Stage0Engine (accepts bot_type)
├── bots/                        # Bot configurations
│   ├── moving_bot_config.py
│   └── restaurant_bot_config.py
└── handlers/                    # Bot handler implementations
    ├── __init__.py              # Handler registration
    ├── moving_bot_handler.py
    └── (future: restaurant_bot_handler.py)
```

## Testing

All 38 tests pass with the universal engine:
```bash
pytest tests/ -v
# ============================= 38 passed in 0.83s ==============================
```

## Next Steps

1. Create handlers for other bot types (restaurant, hotel, etc.)
2. Add bot type selection in HTTP endpoints (e.g., `/twilio/webhook?bot_type=moving_bot_v1`)
3. Add bot type configuration per tenant in database
4. Create admin UI for managing bot types per tenant
5. Add bot type analytics and metrics

## Questions?

- **Q: Can I mix bot types in the same tenant?**
  A: Yes! Each session stores its `bot_type`, so different chats can use different bots.

- **Q: Do I need to change the database schema?**
  A: No! Sessions table already stores `step` as text. We just added `bot_type` and `language` fields (with defaults for backward compatibility).

- **Q: What happens if a bot_type is not registered?**
  A: `UniversalEngine` raises a `ValueError` with available bot types listed.

- **Q: Can I test a new bot without deploying?**
  A: Yes! Just register your handler and use it in tests or dev endpoints.
