"""Shared plumbing for the local-development fixture system.

Hermes renders account, credits, billing and subscription state from the Nous
Portal and from live inference response headers. ``HERMES_DEV_*_FIXTURE`` env
vars let a developer substitute controlled offline fixtures for those live
sources so every state is testable without a portal account or real spend.

Two invariants hold everywhere a fixture is read — both are enforced here so
every consumer behaves the same way:

* **Prod-leak guard.** A fixture activates only in local development:
  ``HERMES_DEV=1`` (the master switch) or the fixture's own master flag
  (``HERMES_DEV_CREDITS`` gates the credits fixtures, which would otherwise
  fabricate a live-session balance). With no fixture vars set, production
  billing/auth/credits behavior is byte-identical.
* **Fail closed on an unknown name.** When a fixture env var is set but names
  no known state, readers must NOT fall through to the live portal (the
  developer believes they are offline). They return the surface's
  "unavailable" state and log a warning; a typo is a config error, never a
  silent production request.

Shared display identity (org + portal) lives here so the billing and
subscription fixtures render the same org/URL instead of duplicating it.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from utils import is_truthy_value

logger = logging.getLogger(__name__)

#: Master local-development switch. ``HERMES_DEV=1`` activates every fixture.
DEV_FIXTURE_MASTER_ENV = "HERMES_DEV"

#: Shared fixture portal origin + org identity (billing / subscription fixtures).
DEV_PORTAL_URL = "https://portal.nousresearch.com/billing"
DEV_ORG = {"org_id": "org_acme", "org_slug": "acme", "org_name": "Acme Inc"}


def fixtures_enabled(*masters: str) -> bool:
    """Prod-leak guard: True only in local development.

    ``HERMES_DEV=1`` is the master switch; a fixture may additionally carry its
    own master flag (the credits fixtures gate on ``HERMES_DEV_CREDITS``). An
    empty ``masters`` tuple means only ``HERMES_DEV`` activates fixtures.
    """
    if is_truthy_value(os.environ.get(DEV_FIXTURE_MASTER_ENV)):
        return True
    return any(is_truthy_value(os.environ.get(m)) for m in masters)


def read_fixture_env(env_var: str, *masters: str) -> Optional[str]:
    """Raw fixture name from *env_var* (stripped, unmodified), or None.

    None means "no fixture active": the env var is unset/blank, or the
    prod-leak guard is closed. Callers lower-case / alias as their own names
    require and treat any non-None value as "a fixture was requested".
    """
    if not fixtures_enabled(*masters):
        return None
    name = (os.environ.get(env_var) or "").strip()
    return name or None


def log_unknown_fixture(env_var: str, name: str) -> None:
    """Warn that *env_var* names no known fixture state; callers then fail closed."""
    logger.warning(
        "%s=%r names no known fixture state — failing closed (no live source consulted)",
        env_var,
        name,
    )
