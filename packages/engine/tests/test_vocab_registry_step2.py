"""Versioning, collision safety, and exact-surface vocabulary regressions."""

from pathlib import Path

import pytest

from ats_engine.parsing.vocab import VOCAB_VERSION, vocabulary_collisions, vocabulary_entry
from ats_engine.pramana.requirements import _jd_parse_cache_key, extract_requirements

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"


@pytest.mark.parametrize("surface", ["ReactJS", "React.js", "React JS"])
def test_react_aliases_preserve_the_exact_jd_surface(surface: str) -> None:
    requirements = extract_requirements(f"Required Qualifications:\nExperience with {surface}.\n")

    react = next(item for item in requirements if item.canonical == "react")

    assert react.surface == surface


@pytest.mark.parametrize(
    ("surface", "canonical", "display", "category"),
    [
        ("NestJS", "nestjs", "NestJS", "framework"),
        ("Redux", "redux", "Redux", "framework"),
        ("NoSQL", "nosql", "NoSQL", "database"),
        ("RabbitMQ", "rabbitmq", "RabbitMQ", "messaging"),
        ("GraphQL", "graphql", "GraphQL", "integration"),
        ("responsive design", "responsive design", "responsive design", "web_development"),
        ("component libraries", "component libraries", "component libraries", "web_development"),
        ("design systems", "design systems", "design systems", "web_development"),
    ],
)
def test_step2_entries_have_stable_identity_and_display(
    surface: str, canonical: str, display: str, category: str
) -> None:
    entry = vocabulary_entry(surface)

    assert entry is not None
    assert (entry.canonical, entry.display, entry.category) == (canonical, display, category)


def test_registry_has_no_alias_collision_or_substring_hazards() -> None:
    assert vocabulary_collisions() == ()


def test_longest_match_keeps_react_native_and_database_names_distinct() -> None:
    jd = """Required Qualifications:
Experience with React Native, ReactJS, SQL, NoSQL, and PostgreSQL.
"""

    canonicals = {item.canonical for item in extract_requirements(jd)}

    assert {"react native", "react", "sql", "nosql", "postgresql"} <= canonicals


def test_vocabulary_version_is_part_of_the_jd_parse_cache_key() -> None:
    assert VOCAB_VERSION
    assert _jd_parse_cache_key("Required: Python") == (VOCAB_VERSION, "Required: Python")


def test_gold_title_ai_and_responsive_surface_are_now_extracted() -> None:
    latent = extract_requirements((FIXTURES / "latentview_bi_ai" / "job_description.txt").read_text())
    cgi = extract_requirements((FIXTURES / "cgi_fullstack_java_angular" / "job_description.txt").read_text())

    assert next(item for item in latent if item.canonical == "artificial intelligence").surface == "AI"
    responsive = next(item for item in cgi if item.canonical == "responsive design")
    assert responsive.surface == "responsive user interfaces"
