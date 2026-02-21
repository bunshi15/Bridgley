# EPIC B — Dispatch Layer Evolution

**Epic ID:** B
**Status:** Iteration 1 Complete
**Depends On:** EPIC A (Platform Isolation)
**Independent From:** EPIC C (LLM)

---

# 0. Strategic Boundary

Dispatch must interact with Lead Core **only via events or jobs**.

Lead Core must never contain executor logic.

---

# B1 — Operator Fallback (Manual Copy) ✅ DONE

Operator receives:

1. Full lead
2. Crew-safe message (copy-ready)

CrewLeadView is allowlist-only DTO.

No PII leakage.

---

# B1.5 — Runtime Isolation Alignment (NEW)

## Objective

Ensure dispatch code runs independently from bot engines.

### Required Structure

```
app/core/dispatch/
    crew_view.py
    services.py
    jobs.py
    events.py
```

Dispatch must not import bot handlers.

Dispatch jobs executed only under:

```
WORKER_ROLE=dispatch
```

## Definition of Done

* dispatch-worker runs without loading bot modules
* core-worker unaffected by dispatch changes

---

# B2 — Automatic Publish

## Objective

Publish CrewLeadView automatically to executor channel.

Triggered by:

```
LeadFinalized
```

Job:

```
dispatch_publish
```

Status:

```
NEW → PUBLISHED
```

## DoD

* Message sent
* crew_message_id stored
* Idempotent by key: lead_id + publish_v1

---

# B3 — Claim Mechanism

Command:

```
/claim <lead_id>
```

Flow:

* Validate PUBLISHED
* Set CLAIMED
* Notify operator
* Atomic transaction

---

# B4 — Controlled PII Release

Command:

```
/release <lead_id>
```

Allowed only for operator.

Status:

```
DETAILS_RELEASED
```

FullLead sent privately.

---

# EPIC B Completion Criteria

* Fully automated dispatch possible
* Operator-controlled fallback still works
* Dispatch deployable separately
* No modification required in Lead Core

---
