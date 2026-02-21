# EPIC C — Moving Bot v2 (LLM Engine)

**Epic ID:** C
**Status:** Not Started
**Depends On:** EPIC A (Platform Isolation)
**Independent From:** EPIC B (Dispatch)

---

# 0. Mandatory Prerequisite

EPIC A must be completed before starting C0.

Reason:

* v2 must be enableable/disableable via `ENABLED_BOTS`
* Must not share worker role with dispatch
* Must not modify Lead Core

---

# Architectural Principle

LLM is:

* Extractor
* Gap detector
* Controlled question generator

LLM is NOT:

* Pricing engine
* Validator
* Dispatcher

Lead Core remains authority.

---

# C0 — Engine Skeleton

## Objective

Introduce `moving_bot_v2_handler.py` without LLM logic.

Enabled only when:

```
ENABLED_BOTS=moving_bot_v2
```

Tenant routing directs traffic to v2.

## DoD

* v2 runs isolated
* v1 unaffected
* Can switch engines via ENV

---

# C1 — Fallback Parser Mode

LLM invoked only when:

* Free-text parsing fails
* User sends complex message

Strict JSON schema output.

Safe fallback on invalid output.

## DoD

* 70%+ extraction accuracy on messy input
* Max N calls/session
* Circuit breaker implemented

---

# C2 — Controlled Question Loop

Rules:

* One question per turn
* Max N clarification turns
* Questions only from allowlist

After N:

* Draft lead
* Flag for operator follow-up

---

# Privacy Alignment with Dispatch

CrewLeadView built only from normalized fields.

Raw user text never sent to crew channel.

LLM `notes_safe` disabled in MVP.

---

# EPIC C Completion Criteria

* Improved lead completeness
* No regression in v1
* Can disable v2 instantly
* No dispatch coupling

---
