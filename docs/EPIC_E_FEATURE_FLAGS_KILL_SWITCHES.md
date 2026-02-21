# EPIC E — Feature Flags & Kill Switches (Safe Degradation)

**Epic ID:** E
**Status:** Ready
**Depends On:** EPIC A ✅ (у тебя уже есть Platform Isolation)
**Primary Value:** Ability to disable risky functionality instantly, minimize production damage, reduce pressure to “cover all edge cases”.

---

## 0. Goal

Provide a controlled way to:

* disable pricing calculator
* disable specific pricing factors (items/extras/multi-pickup)
* force manual operator flow
* switch between bot engines (already done via `ENABLED_BOTS`)
* reduce blast radius of bugs

**Key constraint:** must be usable in production quickly and safely.

---

## 1. Design Principles

1. **Fail closed** for risky features (prefer disabling calculator over sending wrong prices).
2. **Per-tenant** capability flags (investor_01 can differ from investor_02).
3. **Runtime toggles** (ideally no restart).
4. **Visibility**: every user-facing calculation must include `calc_mode` / `pricing_enabled` status in internal logs.

---

## 2. Flag Storage Options (MVP → Mature)

### Option A (MVP, very fast): Tenant config JSON

Flags live in existing tenant config file(s).
Requires redeploy/restart to apply.

### Option B (Better): DB-backed flags (recommended)

Table `tenant_feature_flags` with `tenant_id`, `key`, `value`, `updated_at`.

Benefits:

* toggle without redeploy
* audit trail
* operator/admin UI later

### Option C (Future): Remote config service

Not needed now.

**Recommendation:** Start with **Option A**, then migrate to **Option B** once stable.

---

## 3. Flags Spec (Initial Set)

### Global bot behavior

* `features.pricing.enabled` (bool)
* `features.pricing.mode` (`"estimate" | "disabled" | "manual_only"`)
* `features.geo.enabled` (bool)
* `features.multi_pickup.enabled` (bool)

### Pricing factors (granular kill switches)

* `features.pricing.factor.route` (bool)
* `features.pricing.factor.items` (bool)
* `features.pricing.factor.extras` (bool)
* `features.pricing.factor.floors` (bool)

### Output controls

* `features.pricing.show_range_to_client` (bool)
* `features.pricing.show_range_to_operator` (bool)  *(usually true)*

---

## 4. Behavior Matrix (What happens when disabled)

### 4.1 If `features.pricing.enabled = false`

Bot must:

* collect lead as usual
* **NOT** show price range to client
* send operator message with: “Pricing disabled; manual quote required”
* set lead metadata: `pricing_disabled_reason` if available

### 4.2 If `features.pricing.mode = "manual_only"`

Bot:

* does not compute estimate
* explicitly tells client: “We’ll confirm price after details”
* prioritizes lead completeness questions

### 4.3 If multi-pickup disabled

Bot:

* allows only Pickup 1 + Destination
* if user gives multiple pickups → operator follow-up

---

## 5. Implementation Units

### E1 — Add Flag Resolution Layer (single source of truth)

**Goal:** one function that returns boolean/value flags for a tenant.

Add:

* `FeatureFlagService.get(tenant_id, key, default)`
* `FeatureFlags` DTO

**DoD**

* all flag reads go through this service
* defaults defined centrally

---

### E2 — Pricing Kill Switch

**Goal:** wrap pricing calculation in a feature gate.

Where:

* whichever module calls `estimate_price()` / pricing engine

Logic:

* if disabled → skip compute and set “manual quote” messaging

**DoD**

* can disable pricing without breaking lead creation
* operator message includes status

---

### E3 — Granular Factor Flags

**Goal:** disable parts of pricing to stop blast radius.

Example:

* disable `items` factor if items parsing is unstable (like your current bug)

**DoD**

* flags affect computation deterministically
* tests for each factor off/on

---

### E4 — Safe Messaging Templates

**Goal:** no confusing user output when calculator off.

Add explicit templates:

* client: “We will confirm final quote”
* operator: “pricing disabled / manual quote required”
* crew: never contains pricing if pricing disabled

**DoD**

* no price printed when disabled (unless configured)

---

### E5 — Runtime Toggle Interface (choose one)

**Option 1 (fast):** operator command

* `/feature pricing off`
* `/feature pricing on`

**Option 2:** admin endpoint (secured)

* `POST /admin/tenants/{id}/flags`

**DoD**

* flags change without redeploy (if Option B)
* audit log exists (even simple)

---

## 6. Testing Strategy

Minimum tests:

* lead flow works with pricing enabled/disabled
* output does not contain currency when disabled
* operator always receives enough info to price manually

---

## 7. Rollout Strategy

1. Implement E1 + E2 first (biggest value)
2. Use it during EPIC D development (turn off items factor temporarily if needed)
3. Add E3 when you hit the next fragile domain

---

## 8. Exit Criteria

* You can disable pricing in < 2 minutes
* You can disable only “items factor” in < 2 minutes
* No redeploy required (if DB flags implemented)
* Operator flow remains functional

---

# Notes

This epic is explicitly designed to accept imperfect edge-case coverage while maintaining production trust.

---
