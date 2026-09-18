"""Tests for agent/dev_fixtures.py — the shared local-development fixture plumbing.

Behavior contracts (not change-detectors): the prod-leak gate (HERMES_DEV is the
master switch; a per-area master flag also opens its own fixtures), raw env reads
through the gate, and the fail-closed-on-unknown logging contract.
"""

from __future__ import annotations

from agent.dev_fixtures import (
    DEV_ORG,
    DEV_PORTAL_URL,
    fixtures_enabled,
    log_unknown_fixture,
    read_fixture_env,
)


def test_master_switch_opens_every_fixture(monkeypatch):
    monkeypatch.delenv("HERMES_DEV", raising=False)
    monkeypatch.delenv("HERMES_DEV_CREDITS", raising=False)
    assert fixtures_enabled() is False
    assert fixtures_enabled("HERMES_DEV_CREDITS") is False
    monkeypatch.setenv("HERMES_DEV", "1")
    assert fixtures_enabled() is True
    assert fixtures_enabled("HERMES_DEV_CREDITS") is True


def test_area_master_opens_only_its_own_fixture(monkeypatch):
    monkeypatch.delenv("HERMES_DEV", raising=False)
    monkeypatch.setenv("HERMES_DEV_CREDITS", "1")
    # No master flags at all -> only HERMES_DEV counts.
    assert fixtures_enabled() is False
    # The credits master opens a credits fixture...
    assert fixtures_enabled("HERMES_DEV_CREDITS") is True
    # ...but a fixture without that master stays closed.
    assert fixtures_enabled("HERMES_DEV_OTHER") is False


def test_read_fixture_env_unset_returns_none(monkeypatch):
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.delenv("HERMES_DEV_BILLING_FIXTURE", raising=False)
    assert read_fixture_env("HERMES_DEV_BILLING_FIXTURE") is None


def test_read_fixture_env_gate_closed_returns_none(monkeypatch):
    monkeypatch.delenv("HERMES_DEV", raising=False)
    monkeypatch.setenv("HERMES_DEV_BILLING_FIXTURE", "card")
    assert read_fixture_env("HERMES_DEV_BILLING_FIXTURE") is None


def test_read_fixture_env_strips_but_preserves_case(monkeypatch):
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_CREDITS_FIXTURE", "  Depleted  ")
    # Raw value (stripped); consumers lower-case at their own lookup, and a FILE
    # PATH must not be lower-cased by the shared reader.
    assert (
        read_fixture_env("HERMES_DEV_CREDITS_FIXTURE", "HERMES_DEV_CREDITS")
        == "Depleted"
    )


def test_read_fixture_env_blank_is_none(monkeypatch):
    monkeypatch.setenv("HERMES_DEV", "1")
    monkeypatch.setenv("HERMES_DEV_BILLING_FIXTURE", "   ")
    assert read_fixture_env("HERMES_DEV_BILLING_FIXTURE") is None


def test_log_unknown_fixture(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        log_unknown_fixture("HERMES_DEV_BILLING_FIXTURE", "bogus")
    assert any(
        "HERMES_DEV_BILLING_FIXTURE" in r.message and "failing closed" in r.message
        for r in caplog.records
    )


def test_shared_fixture_identity_constants():
    # The billing + subscription fixtures render the same org and portal origin.
    assert DEV_ORG == {"org_id": "org_acme", "org_slug": "acme", "org_name": "Acme Inc"}
    assert DEV_PORTAL_URL == "https://portal.nousresearch.com/billing"
