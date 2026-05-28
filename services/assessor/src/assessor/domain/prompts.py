"""Backwards-compat shim — verdict framework prompts.

The historical single-tenant prompt module. All content now lives in
``assessor.domain.frameworks.verdict``; this file re-exports the public
symbols so any external import path (CLI scripts, tests, third-party tooling
not yet migrated to the framework registry) keeps working.

Phase 10 (plan 10-03 T06): new code SHOULD import from
``assessor.domain.frameworks.verdict`` (or use the registry) directly.
"""

from __future__ import annotations

from assessor.domain.frameworks.verdict import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_OPPORTUNITY_CRITERIA,
    DEFAULT_RISK_CRITERIA,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    RETAIL_RELEVANCE_PROMPT,
    RETAIL_RELEVANCE_SYSTEM,
)

__all__ = [
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_OPPORTUNITY_CRITERIA",
    "DEFAULT_RISK_CRITERIA",
    "PROMPT_VERSION",
    "RESPONSE_SCHEMA",
    "RETAIL_RELEVANCE_PROMPT",
    "RETAIL_RELEVANCE_SYSTEM",
]
