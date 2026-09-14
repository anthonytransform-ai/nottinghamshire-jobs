"""Configurable direct/HTML adapter for academy-trust supplemental routes."""

from .direct_council import DirectCouncilAdapter


class AcademyTrustAdapter(DirectCouncilAdapter):
    """Trust routes share the direct-list lifecycle but retain their own source id."""
