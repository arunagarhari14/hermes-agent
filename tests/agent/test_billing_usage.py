"""Tests for the shared dollar usage model (agent/billing_usage.py).

Behavior contracts: status classification, bar math, fail-open, and the
dollars-only / topup-split invariants the billing UX requires.

Also exercises the ``HERMES_DEV_CREDITS_FIXTURE`` environment variable
gating — when set, ``build_usage_model()`` returns an offline fixture
instead of contacting the portal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from agent.billing_usage import LOW_BALANCE_THRESHOLD_USD, UsageBar, usage_model_from_account


# ── Lightweight stand-ins for the NousPortalAccountInfo shape ────────────────


@dataclass
class _Access:
    subscription_credits_remaining: Optional[float] = None
    purchased_credits_remaining: Optional[float] = None
    total_usable_credits: Optional[float] = None


@dataclass
class _Sub:
    plan: Optional[str] = None
    monthly_credits: Optional[float] = None
    current_period_end: Optional[str] = None


@dataclass
class _Account:
    logged_in: bool = True
    paid_service_access: Optional[bool] = None
    paid_service_access_info: Optional[_Access] = None
    subscription: Optional[_Sub] = None


def _acct(**over):
    return _Account(**over)


class _Boom:
    @property
    def logged_in(self):
        raise RuntimeError("kaboom")




@pytest.mark.parametrize(
    "account,expected",
    [
        # no plan, no balance -> free
        (_acct(paid_service_access_info=_Access()), "free"),
        # paid access explicitly lost -> depleted
        (_acct(paid_service_access=False, subscription=_Sub(plan="Plus", monthly_credits=20.0),
               paid_service_access_info=_Access(subscription_credits_remaining=0.0, total_usable_credits=0.0)), "depleted"),
        # above threshold -> healthy
        (_acct(paid_service_access=True, subscription=_Sub(plan="Plus", monthly_credits=20.0),
               paid_service_access_info=_Access(subscription_credits_remaining=14.0, total_usable_credits=14.0)), "healthy"),
        # under $5 spendable -> low
        (_acct(paid_service_access=True, subscription=_Sub(plan="Plus", monthly_credits=20.0),
               paid_service_access_info=_Access(subscription_credits_remaining=3.4, total_usable_credits=3.4)), "low"),
        # exactly $5 -> healthy (the threshold boundary is exclusive)
        (_acct(paid_service_access=True, subscription=_Sub(plan="Plus", monthly_credits=20.0),
               paid_service_access_info=_Access(subscription_credits_remaining=5.0, total_usable_credits=5.0)), "healthy"),
        # top-up only, no plan -> usable (healthy), not free
        (_acct(paid_service_access=True, paid_service_access_info=_Access(purchased_credits_remaining=30.0, total_usable_credits=30.0)), "healthy"),
    ],
)
def test_status_classification(account, expected):
    m = usage_model_from_account(account)
    assert m.available is True
    assert m.status == expected






def test_plan_bar_spent_and_pct():
    m = usage_model_from_account(
        _acct(paid_service_access=True, subscription=_Sub(plan="Plus", monthly_credits=20.0),
              paid_service_access_info=_Access(subscription_credits_remaining=14.0, total_usable_credits=14.0))
    )
    bar = m.plan_bar
    assert bar is not None and bar.kind == "plan"
    assert (bar.remaining_usd, bar.total_usd, bar.pct_used) == (14.0, 20.0, 30)
    assert bar.spent_usd == pytest.approx(6.0)




def test_topup_bar_is_full_with_no_denominator():
    m = usage_model_from_account(
        _acct(paid_service_access=True, subscription=_Sub(plan="Plus", monthly_credits=20.0),
              paid_service_access_info=_Access(subscription_credits_remaining=14.0, purchased_credits_remaining=12.0, total_usable_credits=26.0))
    )
    tb = m.topup_bar
    assert tb is not None and tb.kind == "topup"
    assert tb.remaining_usd == 12.0 and tb.fill_fraction == 1.0 and tb.pct_used is None
    assert m.total_spendable_usd == 26.0 and m.has_topup is True


def test_dev_credits_fixture_healthy(monkeypatch):
    """When HERMES_DEV_CREDITS_FIXTURE=healthy, build_usage_model returns a healthy model
    without contacting the portal."""
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "healthy")
    from agent.billing_usage import build_usage_model
    m = build_usage_model(timeout=5)
    assert m.available is True
    assert m.status == "healthy"
    assert m.plan_name == "Plus"
    assert m.subscription_remaining_usd == 14.0
    assert m.total_spendable_usd == 14.0


def test_dev_credits_fixture_depleted(monkeypatch):
    """When HERMES_DEV_CREDITS_FIXTURE=depleted, build_usage_model returns a depleted model
    without contacting the portal."""
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "depleted")
    from agent.billing_usage import build_usage_model
    m = build_usage_model(timeout=5)
    assert m.available is True
    assert m.status == "depleted"
    assert m.plan_name == "Plus"


def test_dev_credits_fixture_low(monkeypatch):
    """When HERMES_DEV_CREDITS_FIXTURE=low, build_usage_model returns a low-balance model
    without contacting the portal."""
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "low")
    from agent.billing_usage import build_usage_model
    m = build_usage_model(timeout=5)
    assert m.available is True
    assert m.status == "low"
    assert m.plan_name == "Plus"


def test_dev_credits_fixture_inert_without_gate(monkeypatch):
    """A stray HERMES_DEV_CREDITS_FIXTURE with no dev gate must NOT activate: the model
    falls through to the real (logged-out) path instead of fabricating a balance."""
    import agent.billing_usage as bu

    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "healthy")
    monkeypatch.delenv("HERMES_DEV", raising=False)
    monkeypatch.delenv("HERMES_DEV_CREDITS", raising=False)
    monkeypatch.setattr(bu, "nous_logged_in", lambda: False)
    monkeypatch.setattr(bu, "fetch_nous_account", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("portal contacted")))
    m = bu.build_usage_model(timeout=5)
    # Not the healthy fixture (that would be available=True); the logged-out fail-open state.
    assert m.available is False


def test_dev_credits_fixture_unset_falls_through_to_real_path(monkeypatch):
    """With the fixture var unset, build_usage_model uses the real (logged-out) path."""
    import agent.billing_usage as bu

    monkeypatch.delenv("HERMES_DEV_CREDITS_FIXTURE", raising=False)
    monkeypatch.setattr(bu, "nous_logged_in", lambda: False)
    m = bu.build_usage_model(timeout=5)
    assert m.available is False  # fail-open: logged out, no fixture


def test_dev_credits_fixture_unknown_fails_closed(monkeypatch):
    """An unknown fixture name must never fall through to the live portal — the model
    fails closed to available=False even when the account would otherwise be live."""
    import agent.billing_usage as bu

    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "not-a-real-state")
    monkeypatch.setattr(bu, "nous_logged_in", lambda: True)
    monkeypatch.setattr(bu, "fetch_nous_account", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("portal contacted")))
    m = bu.build_usage_model(timeout=5)
    assert m.available is False
    assert m.status == "free"


def test_dev_credits_fixture_free(monkeypatch):
    """HERMES_DEV_CREDITS_FIXTURE=free renders the no-plan fixture state."""
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "free")
    from agent.billing_usage import build_usage_model
    m = build_usage_model(timeout=5)
    assert m.available is True
    assert m.status == "free"
    assert m.plan_name is None






