# Stage0 — Deployment & Modularization Value Development Plan

**Project:** Stage0 Moving Bot
**Author:** Internal Architecture Plan
**Goal:**

1. Introduce dispatch foundation without destabilizing current production.
2. Enable modular multi-engine bot deployment.
3. Allow dispatch layer to be deployed independently.
4. Prepare safe groundwork for LLM-based `moving_bot_v2`.

---

# 0. Core Architectural Principle

We preserve:

> Lead Core = stable, deterministic, business-critical.

Everything new must be:

* Additive
* Isolated
* Feature-flagged
* Tenant-controlled
* Deployable independently where possible

No rewrite. No mutation of existing flows.

---

# 1. Phase 1 — Dispatch Foundation (Low Risk, Immediate Business Value)

## Objective

Add dispatch groundwork and second operator message (crew-safe)
WITHOUT modifying moving_bot_v1 dialogue logic.

## 1.1 Add CrewLeadView (Allowlist DTO)

Create new module:

```
app/core/dispatch/crew_view.py
```

### CrewLeadView must include ONLY:

* route (locality names, no full address)
* date
* time window
* volume category
* floors + elevator flags
* items/extras
* estimated price range
* internal lead reference ID

### Explicitly EXCLUDED:

* full address
* name
* phone
* free text notes
* PII

This must be constructed from normalized fields — never from raw text.

---

## 1.2 Hook into LeadFinalized

In the existing lead finalization logic:

Add single integration point:

```
dispatch.publish_lead_finalized(lead_id)
```

MVP implementation may directly enqueue a job instead of building event bus.

No other business logic changes.

---

## 1.3 Add Dispatch Job (Operator Crew Message)

New job:

```
app/jobs/dispatch_notify_operator.py
```

Behavior:

1. Build CrewLeadView from lead_id
2. Send second message to operator
3. Controlled by tenant config flag:

```
dispatch.operator.send_crew_fallback = true/false
```

---

## Phase 1 Done Criteria

* moving_bot_v1 unchanged in behavior
* Operator receives second crew-safe message
* No PII leaks
* Fully toggleable per tenant

---

# 2. Phase 2 — Modular Bot Engine Registration

## Objective

Allow multiple bot engines without hard-coded registry side effects.

## Current Problem

Handlers are registered statically in:

```
app/core/handlers/__init__.py
```

This prevents modular deployment.

---

## 2.1 Introduce Handler Registry Module

Create:

```
app/core/handlers/registry.py
```

### Add:

```
def register_handlers(enabled_bots: list[str]) -> None
```

Move registration logic here.

---

## 2.2 Remove Side Effects from **init**.py

`__init__.py` should export handlers but NOT auto-register.

No implicit registration at import time.

---

## 2.3 Introduce Environment Controlled Engine Selection

Environment variable:

```
ENABLED_BOTS=moving_bot_v1,moving_bot_v2
```

At application startup:

```
register_handlers(parse_enabled_bots())
```

---

## Phase 2 Done Criteria

* Application starts with selected bot engines only
* moving_bot_v1 fully operational
* No behavior change to existing tenants
* Future bots can be added without touching core logic

---

# 3. Phase 3 — Dispatch Layer Independent Deployment

## Objective

Enable dispatch logic to be deployed separately from bot core.

---

## 3.1 Separate Runtime Profiles

Single repository, multiple entrypoints:

### Containers:

* core-api
* core-worker
* dispatch-worker

---

## 3.2 Dispatch Worker Isolation

Dispatch worker must depend on:

* Database
* Notification channels
* Dispatch modules

Dispatch worker must NOT depend on bot dialogue modules.

---

## 3.3 Docker Compose Structure

```
services:
  core-api:
  core-worker:
  dispatch-worker:
```

Optional:

```
profiles:
  core
  dispatch
```

---

## Phase 3 Done Criteria

* Dispatch worker can be restarted independently
* Core bot deployment unaffected by dispatch changes
* No circular imports between dispatch and handlers

---

# 4. Phase 4 — Moving Bot v2 (LLM Engine)

Only after Phases 1–3 are stable.

## Objective

Introduce LLM-powered moving bot as separate engine.

---

## 4.1 New Handler

```
app/core/handlers/moving_bot_v2_handler.py
```

Must produce the same normalized data structure expected by Lead Core.

LLM is:

* extractor
* gap detector
* question generator

LLM is NOT:

* pricing engine
* validator
* dispatcher

---

## 4.2 Tenant Separation

Recommended:

* Separate tenant
* Separate number
* Separate analytics tracking

---

## 4.3 Iterative Activation Strategy

Mode 1 — Fallback Parser
LLM used only for messy free-text.

Mode 2 — Controlled Question Loop
LLM allowed 1 question per turn, max N turns.

Mode 3 — Full structured dialogue.

---

## Phase 4 Done Criteria

* LLM engine does not modify Lead Core logic
* Can disable via ENV without code change
* No dispatch impact

---

# 5. Deployment Evolution Strategy

## Stage A (Now)

Single VPS (CX33)
Single repo
Multiple containers

## Stage B (After Growth)

Separate:

* Dispatch service
* Bot engine service
* Possibly read-only replica for analytics

No immediate infra scaling required.

---

# 6. Risk Control Matrix

| Risk                      | Mitigation                      |
| ------------------------- | ------------------------------- |
| Breaking current bot      | v1 untouched                    |
| PII leak in dispatch      | Allowlist DTO only              |
| Overcoupling modules      | Dispatch isolated package       |
| Future scaling complexity | Engine registry abstraction     |
| LLM instability           | Separate handler + feature flag |

---

# 7. Rollback Strategy

At any time:

* Disable dispatch via config flag
* Remove dispatch-worker container
* Set `ENABLED_BOTS=moving_bot_v1`

No database schema rollback required.

---

# 8. Success Metrics

Phase 1:

* Operator efficiency improved
* No PII incident

Phase 2:

* Ability to run different bot engines per deployment

Phase 3:

* Dispatch changes do not require bot restart

Phase 4:

* Improved lead completeness
* Reduced manual clarification rate

---

# 9. Long-Term Architectural Vision

After stabilization:

* Dispatch becomes orchestration layer
* Bot engines become pluggable “input adapters”
* Lead Core remains deterministic business authority
* LLM becomes controlled augmentation layer

---

# Final Summary

This plan ensures:

* Zero-risk incremental evolution
* Immediate dispatch value
* Future multi-engine scalability
* Safe LLM integration path
* Modular deployability
* Clean rollback options



