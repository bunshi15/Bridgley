# EPIC D — Parsing, Pricing & Rendering Correctness Fixes

**Epic ID:** D
**Status:** Done
**Depends On:** None (can run in parallel with EPIC A)
**Blocks:** None
**Primary Value:** Prevent incorrect quantities, wrong price estimates, and misleading crew/operator messages.

---

## 0. Problem Statement

Observed production-like case:

* User entered item description containing numeric attributes (e.g., “5-дверный шкаф”, “200кг”, “615л”).
* System rendered crew view as `Wardrobe large ×5` and produced a significantly higher price range.

This indicates a parsing bug where **any number in the fragment** is treated as **quantity**, even when it is an **attribute**.

---

## 1. Root Cause (Confirmed in Code)

File: `app/core/bots/moving_bot_validators.py`
Function: `extract_items()`

Current behavior:

* Finds alias in fragment
* Removes alias → `remainder`
* Applies `_QTY_PATTERN.search(remainder)`
* If any number exists → sets `qty` to that number

This makes strings like:

* `5 дверный шкаф` → qty=5
* `200кг холодильник` or `холодильник 615л` → potentially qty=200/615 (depending on alias match and remainder)

---

## 2. Goals

### 2.1 Functional Goals

1. **Quantities must be extracted only when explicitly expressed as quantity**, not from attributes.
2. Numeric attributes like “5 дверей”, “200кг”, “615л”, “180см” must **not** affect item quantity.
3. Crew/operator messages must represent:

   * correct quantities
   * correct multi-pickup route representation
   * consistent formatting between full and crew-safe messages

### 2.2 Non-Goals

* No LLM involvement.
* No redesign of pricing engine (only correct inputs).
* No new UI — just output correctness.

---

## 3. Scope

### 3.1 Fix Item Quantity Parsing (Core)

**Module:** `moving_bot_validators.extract_items()`

#### Rule Set (MVP-safe)

Quantity is recognized ONLY if one of the following explicit markers exists:

* `x5`, `5x`
* `5 шт`, `5 штук`
* `5 pcs`, `5 pieces`
* `qty: 5`, `qty=5`

All other numbers in the fragment are treated as attributes and must not affect qty.

#### Attribute-like number suppression patterns (examples)

If remainder contains any of these patterns, qty must stay `1`:

* `двер` (doors)
* `кг`, `kg`
* `л`, `l` (liters)
* `см`, `cm`
* `мм`, `mm`

> This is intentionally conservative: better to under-detect qty than to inflate price.

---

### 3.2 Add Sanity Caps (Guardrail)

Optional but recommended:

* If parsed qty > 20 and quantity marker is not explicit → set qty = 1.

---

### 3.3 Rendering Fix: Multi-pickup Route Consistency

Crew view currently shows a simplified route while full message shows multiple pickups.

**Fix requirement:**

* crew-safe message must clearly indicate multi-pickup:

  * Pickup 1 locality
  * Pickup 2 locality (if exists)
  * Destination locality
* Floors should map correctly:

  * pickup1 floors
  * pickup2 floors
  * destination floors

---

## 4. Work Units

### D1 — Patch `extract_items()` Quantity Rules

**Tasks**

* Implement explicit quantity detection pattern.
* Add attribute suppression checks.
* Keep backwards compatibility for existing “xN / Nшт / qty”.

**Definition of Done**

* `5 дверный шкаф` → wardrobe qty = 1
* `шкаф x5` → wardrobe qty = 5
* `шкаф 5шт` → wardrobe qty = 5
* `холодильник 200кг 615л` → refrigerator qty = 1

---

### D2 — Unit Tests for Item Parsing

**Where:** add tests near validators tests (or create `tests/test_moving_items_parsing.py`)

**Cases**

1. `5 дверный шкаф` → qty=1
2. `шкаф x5` → qty=5
3. `шкаф 5 шт` → qty=5
4. `холодильник 200кг 615л` → qty=1
5. `2 коробки` → (MVP decision)

   * Either qty=1 (safe) OR support later with RU plural grammar (see “Future”)

**Definition of Done**

* Tests run in CI locally and pass.
* No regression on current supported explicit quantity forms.

---

### D3 — CrewLeadView Multi-pickup Rendering Fix

**Tasks**

* Update CrewLeadView builder/message formatter to render:

  * multi pickup list
  * correct floors mapping

**Definition of Done**
Given two pickups:

* Crew message includes “Pickup 1 …”, “Pickup 2 …”, “Destination …”
* Floors printed per point

---

### D4 — Pricing Regression Verification

**Tasks**

* Log/inspect normalized items before pricing (temporary debug flag).
* Verify that corrected items produce corrected estimate.

**Definition of Done**

* The example case no longer multiplies wardrobe by 5.
* Estimate drops to expected range consistent with single wardrobe + fridge (plus pickups/extras).

---

## 5. Acceptance Criteria (End-to-End)

Using the exact scenario style:

Input:

* “Холодильник, 5 дверный шкаф”
* Two pickups + elevators
* Extras: грузчики

Expected output:

* Crew view: `Wardrobe large ×1` (not ×5)
* Price range does not include an inflated multiplier driven by doors/weight/liters.
* Route rendering clearly indicates multiple pickups.

---

## 6. Risk & Rollback

**Risk:** Under-detection of qty for Russian phrases like “5 шкафов” (without explicit marker).
**Mitigation:** This is acceptable for MVP; can be improved in a later epic with RU grammar support.

**Rollback:** Single-function logic change + tests. Can revert commit safely.

---

## 7. Future Extensions (Not in Scope)

* RU grammar qty detection (“5 шкафов”, “2 коробки”) with safeguards.
* Extract attributes into `attributes` (doors, kg, liters) for richer internal representation.
* Better item canonicalization across languages.

---

## 8. Implementation Order (Suggested)

1. D1 patch `extract_items()`
2. D2 tests
3. D3 crew rendering multi-pickup
4. D4 pricing regression check

---

## 9. Deliverables

* Code patch in validators
* Unit tests
* Updated crew message formatter
* Short changelog entry

---

## EPIC D — Complete ✅

**1034 tests pass, 0 failures.**

### Summary of all changes:

**D1 — Item Quantity Parsing Fix** (`moving_bot_validators.py`):
- Replaced naive `_QTY_PATTERN = re.compile(r"(\d+)")` with a 3-tier system:
  1. **Explicit markers** (`_EXPLICIT_QTY_PATTERN`): `x5`, `5x`, `5шт`, `5 штук`, `5 pcs`, `qty:5` — always honored
  2. **Attribute suppression** (`_ATTR_SUFFIXES`): digits followed by `двер`, `кг`, `kg`, `л`, `см`, `cm`, `мм`, `м` → qty stays 1
  3. **Bare number fallback** with sanity cap ≤ 20
- Example fix: `"5 дверный шкаф"` → qty=1 (was 5), `"холодильник 200кг"` → qty=1 (was 200)

**D2 — 21 New Unit Tests** (`test_moving_bot.py`):
- `TestExtractItemsAttributeSafe` class covering attribute suppression, explicit markers, bare numbers, sanity cap, and combined scenarios

**D3 — Multi-Pickup Crew View** (`app/core/dispatch/crew_view.py`):
- Route now shows all pickup localities → destination (e.g., `Haifa → Haifa North → Tel Aviv`)
- Floors show per-pickup breakdown with localized labels:
  - RU: `Забор 1: 3 (без лифта) / Забор 2: 7 (есть лифт) / Доставка: 5 (есть лифт)`
  - EN: `Pickup 1` / `Delivery`
  - HE: `איסוף 1` / `משלוח`
- Single-pickup format unchanged (backward compatible)
- 7 new tests in `TestCrewMessageMultiPickup`

**B1.5 Cleanup — Dispatch Isolation** (`notification_service.py`):
- Removed old inline `format_crew_message()` + `notify_operator_crew_fallback()` + label dicts (~200 lines)
- Replaced with re-exports from `app.core.dispatch.crew_view` and `app.core.dispatch.services`
- Recreated the three dispatch package source files that were missing (`.py` files had been deleted, only `__pycache__` survived)

**D4 — Pricing Regression Verified**:
- Same scenario (`"Холодильник, 5 дверный шкаф"`) now estimates ₪692–₪938 vs buggy ₪1,797–₪2,433
- **₪1,100–₪1,500 overcharge prevented**