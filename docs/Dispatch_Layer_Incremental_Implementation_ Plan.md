# Dispatch Layer — Incremental Implementation Plan

**Project:** Stage0 Bot
**Scope:** Executor group integration without destabilizing existing Client → Operator flow
**Status:** Iterative rollout (Manual → Semi-automatic → Fully automated)

---

# 1. Architectural Principle

## 1.1 Separation of Concerns

The system must remain split into two independent domains:

### A. Lead Core (Stable, Production-Ready)

Responsible for:

* Client conversation
* Data collection
* Validation
* Pricing
* Lead creation
* Operator notification

**Lead Core must NOT contain any executor/group logic.**

---

### B. Dispatch Layer (New, Isolated Feature)

Responsible for:

* Publishing anonymized job summaries
* Handling executor claims
* Managing assignment lifecycle
* Controlling PII release
* Updating group status

Dispatch must interact with Lead Core **only via events or job enqueueing**.

---



# 2. Data Model — Dispatch State

Create a dedicated table (recommended) or extend lead model carefully.

## 2.1 dispatch_state Table (Recommended)

```sql
dispatch_state (
    lead_id UUID PRIMARY KEY,
    status TEXT NOT NULL,

    crew_provider TEXT,
    crew_chat_id TEXT,
    crew_message_id TEXT,

    claimed_by TEXT,
    claimed_at TIMESTAMP,

    operator_confirmed_at TIMESTAMP,

    invoice_status TEXT,
    paid_at TIMESTAMP,

    details_released_at TIMESTAMP,

    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

---

## 2.2 Dispatch Status Enum

```
NEW
PUBLISHED
CLAIMED
OPERATOR_CONFIRMED
INVOICE_SENT
PAID
DETAILS_RELEASED
CANCELLED
EXPIRED
```

This is future-proof and matches your operational model.

---

# 3. Privacy Model

## 3.1 Two Lead Representations

### FullLead (PII)

* Client phone
* Full addresses
* Free text
* Media
* Everything

### CrewLeadView (Sanitized)

Allowlist-based DTO containing only:

* lead_id (shortened)
* from_locality
* to_locality
* date
* time_window
* volume_category
* floors
* elevator info
* item summary
* estimated price range

**Never attempt to “remove PII from text”.
Always build CrewLeadView from explicit allowed fields.**

---

# 4. Event Integration Point

Add a single integration event:

```
LeadFinalized
```

Triggered when:

* Lead is complete
* Operator notification is sent

Dispatch layer subscribes to this event.

This ensures:

* No logic leakage into Core
* Easy enable/disable per tenant
* Clean scalability

---

# 5. Iteration Roadmap

---

# Iteration 1 — Operator Fallback (Manual Copy)

## Objective

Operator receives:

1. Full lead (current behavior)
2. Crew-safe message (copy/paste ready)

## Changes

### 5.1 New Job Type

```
notify_operator_crew_fallback
```

Enqueued on `LeadFinalized` if:

```
dispatch.operator.send_crew_fallback == true
```

---

### 5.2 Crew Message Format

```
📣 FOR CREW (Copy to group)

🧰 Job #0952ef82

Route: Haifa → Kiryat Ata
Date: 23 Feb (Morning)
Volume: 1BR
Floors: 3 → 2 (No elevator)
Extras: Fridge, Washing machine
Estimate: ₪850–₪950
```

No client phone.
No street address.
No links.

---

### 5.3 Config Extension

```json
"dispatch": {
  "operator": {
    "send_full": true,
    "send_crew_fallback": true
  },
  "crew": {
    "enabled": false,
    "provider": null,
    "chat_id": null
  }
}
```

---

# Iteration 2 — Automatic Publish to WhatsApp Crew Channel

## Objective

Automatically send CrewLeadView to executor channel.

### 6.1 Enable Config

```
dispatch.crew.enabled = true
dispatch.crew.provider = "meta"
dispatch.crew.chat_id = "<group or broadcast number>"
```

---

### 6.2 New Job Type

```
dispatch_publish
```

Workflow:

1. Build CrewLeadView
2. Send message via selected provider
3. Store `crew_message_id`
4. Set status = PUBLISHED

---

### Important Note on WhatsApp Groups

Cloud API group support may be limited.

If direct group posting fails:

* Use broadcast model (send to list of executor numbers)
* Or designate a dispatcher number

Telegram integration will be more flexible in Iteration 3.

---

# Iteration 3 — Claim Mechanism

## Objective

Executor can reserve job.

### 7.1 Command

```
/claim <lead_id>
```

### 7.2 Flow

1. Validate lead status == PUBLISHED
2. Check not already claimed
3. Set:

   * status = CLAIMED
   * claimed_by
   * claimed_at
4. Notify operator
5. Update group message:
   “Reserved by @executor”

Must be transactional.

---

# Iteration 4 — Controlled PII Release

## Objective

Executor receives full details only after:

* Operator confirms assignment
* Invoice issued
* Payment received

---

### 8.1 Manual Operator Control (MVP)

Add command:

```
/release <lead_id>
```

Only operator role allowed.

This sets:

```
status = DETAILS_RELEASED
details_released_at = now()
```

And sends FullLead to executor privately.

---

# 6. Job Architecture Alignment

All dispatch logic must be executed through job worker:

* notify_operator_crew_fallback
* dispatch_publish
* dispatch_claim_process
* dispatch_release_details

Never send synchronously inside webhook handler.

---

# 7. Idempotency Rules

Use idempotency keys:

* `lead_id + "crew_fallback_v1"`
* `lead_id + "publish_v1"`
* `lead_id + "release_v1"`

Prevents duplicate messages during retries.

---

# 8. Security Considerations

* Crew messages must never log full payload
* All PII access restricted to operator flows
* Claim operations must be atomic
* Role-based command access required for `/release`

---

# 9. Minimal Implementation Order

1. Add CrewLeadView builder
2. Add fallback notification job (Iteration 1)
3. Add dispatch_state table
4. Add publish job (Iteration 2)
5. Add claim command (Iteration 3)
6. Add release command (Iteration 4)

---

# 10. Strategic Advantage

This architecture allows:

* Different investors using different channels
* WhatsApp-only model
* Telegram-only model
* Hybrid
* Fully automated dispatch
* Or operator-controlled workflow

Without modifying Lead Core again.

