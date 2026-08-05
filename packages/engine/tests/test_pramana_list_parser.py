"""Unit tests for the bracket-aware requirement-list scanner."""

import pytest

from ats_engine.pramana.list_parser import parse_structured_lists
from ats_engine.pramana.requirements import extract_requirements


@pytest.mark.parametrize(
    ("source", "parent", "children"),
    [
        ("ReactJS (hooks, context, and state management)", "ReactJS", ("hooks", "context", "state management")),
        ("messaging queues (Kafka, RabbitMQ)", "messaging queues", ("Kafka", "RabbitMQ")),
        ("frameworks [React/Vue/Svelte]", "frameworks", ("React", "Vue", "Svelte")),
        ("stores {Redis; DynamoDB or MongoDB}", "stores", ("Redis", "DynamoDB", "MongoDB")),
    ],
)
def test_bracket_lists_preserve_parent_children_and_offsets(
    source: str, parent: str, children: tuple[str, ...]
) -> None:
    parsed = parse_structured_lists(source)

    relation = parsed[0]
    assert relation.parent.text == parent
    assert tuple(child.text for child in relation.children) == children
    assert source[relation.parent.start : relation.parent.end] == parent
    for child in relation.children:
        assert source[child.start : child.end] == child.text


def test_nested_lists_return_outer_and_inner_relations() -> None:
    source = "databases: SQL, NoSQL (MongoDB, DynamoDB), and Redis"

    parsed = parse_structured_lists(source)
    by_parent = {relation.parent.text: tuple(child.text for child in relation.children) for relation in parsed}

    assert by_parent["databases"] == ("SQL", "NoSQL", "Redis")
    assert by_parent["NoSQL"] == ("MongoDB", "DynamoDB")


def test_unbalanced_or_mismatched_brackets_are_rejected() -> None:
    assert parse_structured_lists("ReactJS (hooks") == ()
    assert parse_structured_lists("ReactJS (hooks]") == ()


def test_leading_cue_phrases_are_trimmed_with_exact_offsets() -> None:
    source = "tools (including React, such as Vue, and using Svelte)"

    relation = parse_structured_lists(source)[0]

    assert tuple(child.text for child in relation.children) == ("React", "Vue", "Svelte")
    for child in relation.children:
        assert source[child.start : child.end] == child.text


def test_extracted_parenthetical_children_retain_parent_canonical() -> None:
    jd = """Required Qualifications:
Proficiency in Python (BeautifulSoup, Scrapy, Selenium, or Playwright).
"""

    requirements = {item.canonical: item for item in extract_requirements(jd)}

    for child in ("beautifulsoup", "scrapy", "selenium", "playwright"):
        assert requirements[child].parent_canonical == "python"
