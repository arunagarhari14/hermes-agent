"""Tests for the HERMES_DEV_ACCOUNT_FIXTURE local-development account fixture.

Every entitlement / feature-gating / /usage surface reads
``get_nous_portal_account_info``; a fixture there makes the whole layer
offline-testable. Behavior contracts: the prod-leak gate (HERMES_DEV=1), the
per-state entitlement shapes (paid vs free tool pool vs no access), and the
fail-closed unknown-name path (an error info, never a live portal call).
"""

from __future__ import annotations

import pytest

from hermes_cli.nous_account import (
    NousPortalAccountInfo,
    get_nous_portal_account_info,
    reset_nous_portal_account_info_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_nous_portal_account_info_cache()
    yield
    reset_nous_portal_account_info_cache()


def _set_fixture(monkeypatch, name: str):
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_ACCOUNT_FIXTURE", name)


def test_paid_fixture_is_entitled_everywhere(monkeypatch):
    _set_fixture(monkeypatch, "paid")
    info = get_nous_portal_account_info()
    assert isinstance(info, NousPortalAccountInfo)
    assert info.logged_in is True
    assert info.source == "dev-fixture" and info.fresh is True
    assert info.paid_service_access is True
    assert info.tool_gateway_entitled is True
    assert (
        info.tool_gateway_entitled_for("fal-video") is True
    )  # paid funds every category
    assert info.subscription is not None and info.subscription.plan == "Plus"


def test_pool_fixture_is_pool_limited(monkeypatch):
    _set_fixture(monkeypatch, "pool")
    info = get_nous_portal_account_info()
    assert info.logged_in is True and info.paid_service_access is False
    assert info.tool_gateway_entitled is True
    assert info.tool_gateway_entitled_for("fal") is True  # pool funds image
    assert info.tool_gateway_entitled_for("openai-audio") is True
    assert info.tool_gateway_entitled_for("fal-video") is False  # but NOT video


def test_free_fixture_has_no_entitlement(monkeypatch):
    _set_fixture(monkeypatch, "free")
    info = get_nous_portal_account_info()
    assert info.logged_in is True and info.paid_service_access is False
    assert info.tool_gateway_entitled is False
    assert info.tool_gateway_entitled_for("firecrawl") is False


def test_anon_fixture_is_anonymous_tier(monkeypatch):
    _set_fixture(monkeypatch, "anon")
    info = get_nous_portal_account_info()
    assert info.is_anonymous_tier is True
    assert info.is_free_tier is True


def test_logged_out_fixture(monkeypatch):
    _set_fixture(monkeypatch, "logged-out")
    info = get_nous_portal_account_info()
    assert info.logged_in is False
    assert info.source == "dev-fixture"


@pytest.mark.parametrize("alias", ["logged_out", "loggedout", "logged-out"])
def test_logged_out_fixture_aliases(monkeypatch, alias):
    _set_fixture(monkeypatch, alias)
    assert get_nous_portal_account_info().logged_in is False


def test_error_fixture(monkeypatch):
    _set_fixture(monkeypatch, "error")
    info = get_nous_portal_account_info()
    assert info.logged_in is False
    assert info.source == "error"
    assert info.error == "dev account fixture error"


def test_fixture_applies_with_force_fresh(monkeypatch):
    """The short-circuit fires before the force-fresh account fetch, so it stays offline."""
    _set_fixture(monkeypatch, "paid")
    info = get_nous_portal_account_info(force_fresh=True)
    assert info.source == "dev-fixture"
    assert info.paid_service_access is True


def test_fixture_inert_without_dev_gate(monkeypatch):
    """A stray HERMES_DEV_ACCOUNT_FIXTURE with no HERMES_DEV must not fabricate an account."""
    monkeypatch.delenv("HERMES_DEV", raising=False)
    monkeypatch.setenv("HERMES_DEV_ACCOUNT_FIXTURE", "paid")
    info = get_nous_portal_account_info()
    assert info.source != "dev-fixture"
    assert info.logged_in is False  # hermetic env: no real credentials either


def test_unknown_fixture_name_fails_closed(monkeypatch):
    """An unknown name returns an error info with the offending value — never a live portal call."""
    _set_fixture(monkeypatch, "not-a-real-state")
    info = get_nous_portal_account_info()
    assert info.logged_in is False
    assert info.source == "error"
    assert "unknown HERMES_DEV_ACCOUNT_FIXTURE" in (info.error or "")


@pytest.mark.parametrize(
    "name,expected", [("paid", True), ("pool", True), ("free", False)]
)
def test_managed_tools_coarse_gate_via_fixture(monkeypatch, name, expected):
    """The Tool Gateway coarse gate (tools.tool_backend_helpers) is offline-drivable too."""
    _set_fixture(monkeypatch, name)
    from tools.tool_backend_helpers import managed_nous_tools_enabled

    assert managed_nous_tools_enabled() is expected
