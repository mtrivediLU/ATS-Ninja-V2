"""KATA -- Keyword-Anchored Truthful Alignment.

The transformation half of the engine: given a base resume and a job
description, produce a tailored resume that is measurably stronger and
contains no invented fact.

This package currently exposes the Immutable Fact Set, which is the floor
every later stage is checked against.
"""

from ats_engine.kata.facts import (
    FactViolation,
    ImmutableFactSet,
    build_fact_set,
    fact_set_violations,
)

__all__ = [
    "FactViolation",
    "ImmutableFactSet",
    "build_fact_set",
    "fact_set_violations",
]
