# EPIC A — Platform Isolation & Deployability

**Epic ID:** A
**Status:** In Progress
**Depends On:** None
**Blocks:** EPIC B (Dispatch), EPIC C (Moving Bot v2)
**Primary Goal:** Enable independent deployment and parallel feature development.

---

# 0. Strategic Principle

> Structural modularization precedes intelligence expansion.

Lead Core must remain deterministic and stable.
All new features must be deployable, disableable, and isolated.

---

# A1 — Engine Modularization

## Objective

Remove static handler registration and enable runtime-controlled bot engines.

## Required Changes

Create:

```
app/core/handlers/registry.py
```

Add:

```
def register_handlers(enabled_bots: list[str]) -> None
```

Remove auto-registration from:

```
app/core/handlers/__init__.py
```

Add ENV:

```
ENABLED_BOTS=moving_bot_v1
```

Startup:

```
register_handlers(parse_enabled_bots())
```

## Definition of Done

* Service runs with only `moving_bot_v1`
* Adding `moving_bot_v2` via ENV enables it without code change
* No side-effect imports

---

# A2 — Worker Role Separation

## Objective

Separate execution contexts between Core and Dispatch.

Add ENV:

```
WORKER_ROLE=core
WORKER_ROLE=dispatch
```

Core worker loads:

* lead processing
* validation
* pricing
* operator full notifications

Dispatch worker loads:

* notify_operator_crew_fallback
* dispatch_publish
* dispatch_claim_process
* dispatch_release_details

## Definition of Done

* Dispatch worker can be restarted independently
* Core worker works without dispatch enabled
* No circular imports

---

# A3 — Deployment Profiles

## Docker Compose Structure

```
services:
  core-api
  core-worker
  dispatch-worker
```

Optional profiles:

```
profiles:
  core
  dispatch
```

## Definition of Done

* `profile core` launches stable production
* `profile dispatch` adds dispatch logic
* No functional regression

---

# Runtime Contracts (Global Across Epics)

These variables must exist and be consistent in all epics:

```
ENABLED_BOTS
WORKER_ROLE
DISPATCH_ENABLED
```

All job types must have clear ownership (Core vs Dispatch).

---

# EPIC A Completion Criteria

* Engines can be added/removed without code mutation
* Workers isolated
* Dispatch deployable independently
* Rollback to v1 possible in < 1 minute

---
