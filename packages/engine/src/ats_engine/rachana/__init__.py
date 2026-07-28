"""RACHANA -- Resume Alignment through Constrained, Honest and Natural Adaptation.

The transformation half of the engine: given a base resume and a job
description, produce a tailored resume that is measurably stronger and
contains no invented fact.

This package currently exposes the Immutable Fact Set, which is the floor
every later stage is checked against.
"""

from ats_engine.rachana.facts import (
    FactViolation,
    ImmutableFactSet,
    build_fact_set,
    fact_set_violations,
)
from ats_engine.rachana.preservation import (
    TermRegression,
    count_occurrences,
    preserves_jd_terms,
    term_regressions,
)

__all__ = [
    "FactViolation",
    "ImmutableFactSet",
    "TermRegression",
    "build_fact_set",
    "count_occurrences",
    "fact_set_violations",
    "preserves_jd_terms",
    "term_regressions",
]
