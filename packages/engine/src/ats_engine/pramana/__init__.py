"""PRAMANA -- Proven Resume Alignment through Measurable Analysis and Normalized Assessment.

The measurement half of the engine: given a resume and a job description,
return a defensible match score with components and an explanation.

This package owns the **Demand Model** -- the single implementation of
requirement extraction. RACHANA consumes the same requirements, so a term that
never enters this model can never be prioritised, resolved, placed, or scored.
Everything downstream is capped by this module's recall.
"""

from ats_engine.pramana.requirements import (
    JDHygiene,
    extract_requirements,
    filter_hygienic_jd_values,
    is_org_role_reference,
    is_person_name,
    sanitize_jd_for_parsing,
)

__all__ = [
    "JDHygiene",
    "extract_requirements",
    "filter_hygienic_jd_values",
    "is_org_role_reference",
    "is_person_name",
    "sanitize_jd_for_parsing",
]
