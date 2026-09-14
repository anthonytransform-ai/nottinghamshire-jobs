"""Nottingham CVS discovery and linked employer adapter."""

from __future__ import annotations

from .direct_council import DirectCouncilAdapter


class NottinghamCVSAdapter(DirectCouncilAdapter):
    """The direct HTML lifecycle is shared; VCSE scope is enforced downstream."""
