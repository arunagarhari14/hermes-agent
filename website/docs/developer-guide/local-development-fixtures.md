---
title: "Local Development Fixtures"
description: "Offline fixtures for account, credits, billing, and feature-gating surfaces via HERMES_DEV_* env vars"
---

# Local development fixtures

Hermes renders account, credits, billing, and subscription state from the Nous
Portal and from live inference response headers. When you are developing against
the checkout, you usually don't want that: you want controlled offline states so
every screen and notice path is exercisable without a portal account, real spend,
or network access.

That is what the **local development fixture system** is for. It is a thin layer
of env-var-driven fixtures over the existing fail-open builders — production
behavior is byte-identical when no fixture variables are set.

## The master switch

`HERMES_DEV=1` turns on **all** fixtures. It is the only variable a developer
needs to remember; it is already used elsewhere in the checkout to mean "local
development" (container-routing bypass).

```bash
HERMES_DEV=1 HERMES_DEV_BILLING_FIXTURE=card hermes --tui
HERMES_DEV=1 HERMES_DEV_CREDITS_FIXTURE=depleted hermes --tui
HERMES_DEV=1 HERMES_DEV_ACCOUNT_FIXTURE=paid hermes tools
```

The credits fixtures additionally honor `HERMES_DEV_CREDITS=1` (the credits
telemetry dev flag) as an alternative gate.

## Two invariants

1. **Prod-leak guard.** A fixture activates only under the gate above, so a stray
   fixture variable exported in a shell can never fabricate account/balance data
   in a production-ish run.
2. **Fail closed on an unknown name.** When a fixture variable is set but names
   no known state, the reader returns the surface's *unavailable* state and logs
   a warning — it never silently falls through to the live portal (you believe
   you are offline; a typo is a config error, not a production request).

## Fixture variables

| Variable | Gate | States | Drives |
|---|---|---|---|
| `HERMES_DEV_ACCOUNT_FIXTURE` | `HERMES_DEV` | `paid` · `pool` · `free` · `anon` · `logged-out` · `error` | `get_nous_portal_account_info()`: feature gating (`get_nous_subscription_features`), managed-tool entitlement, `managed_nous_tools_enabled`, portal-seeded credits/usage |
| `HERMES_DEV_CREDITS_FIXTURE` | `HERMES_DEV` or `HERMES_DEV_CREDITS` | `healthy` · `sub_50pct` · `sub_75pct` · `sub_90pct` · `grant_exhausted` · `depleted` · `debt` (or a **file path** whose contents name one — re-read every call so `echo depleted > /tmp/cf` flips live) | per-turn credits notices, the session-open seed, `/usage`, `/topup`-adjacent renderers |
| `HERMES_DEV_BILLING_FIXTURE` | `HERMES_DEV` | `nocard` · `card` · `card-sub` · `card-autoreload` · `notadmin` · `billing-off` · `logged-out` | the Remote Spending screens (`build_billing_state`) |
| `HERMES_DEV_SUBSCRIPTION_FIXTURE` | `HERMES_DEV` | `free` · `mid` · `top` · `not-admin` · `downgrade` · `cancel` · `team` · `logged-out` | the `/subscription` screen (`build_subscription_state`) |

The usage bars share `HERMES_DEV_CREDITS_FIXTURE` (states `free` · `healthy` ·
`low` · `topup` · `depleted`) — set it and both `/usage` and `/subscription`
render from the fixture. Aliases (`mid`→`healthy`, `top-up`→`topup`,
`logged_out`→`logged-out`, …) are accepted everywhere.

## Driving the feature-gating layer offline

`HERMES_DEV_ACCOUNT_FIXTURE` is the widest seam: the entire account/entitlement
layer reads `get_nous_portal_account_info()`, so the fixture makes feature
gating fully offline-testable:

- `paid` — subscribed, entitled to every managed-tool category (including video).
- `pool` — $0 account with a live free tool pool: funded categories only, video excluded.
- `free` — named account on a free plan: no paid access, no tool pool.
- `anon` — anonymous free tier (no Nous account behind it).
- `logged-out` / `error` — auth-failure shapes.

Managed-gateway *readiness* additionally needs a token probe; supply a dev value
for `TOOL_GATEWAY_USER_TOKEN` when you need `managed_by_nous` features to resolve
offline:

```bash
HERMES_DEV=1 HERMES_DEV_ACCOUNT_FIXTURE=paid TOOL_GATEWAY_USER_TOKEN=dev hermes tools
```

## Where it lives

Shared plumbing (the gate, the raw read, the fail-closed warning, and the shared
fixture org/portal identity) is in `agent/dev_fixtures.py`; the account fixture
in `hermes_cli/nous_account.py`; the per-surface fixture tables stay beside the
state they render (`agent/credits_tracker.py`, `agent/billing_usage.py`,
`agent/billing_view.py`, `agent/subscription_view.py`).