"""Assessment framework registry.

A *framework* defines how a trending topic is evaluated by the AI: the prompt
shape, the structured JSON contract, and the frontend display component. The
pipeline dispatches per-job to the framework identified by ``framework_id`` on
the ``assessment_jobs`` row (Phase 10 plan 10-03).

Three frameworks ship in v1:
- ``verdict`` — single relevance verdict (the historical pipeline, ported 1:1)
- ``swot`` — strengths / weaknesses / opportunities / threats matrix
- ``pestle`` — political / economic / social / technological / legal /
  environmental cells

Public surface:

    from assessor.domain.frameworks import registry
    fw = registry.get_by_key("verdict")
"""

from assessor.domain.frameworks import registry  # noqa: F401

__all__ = ["registry"]
