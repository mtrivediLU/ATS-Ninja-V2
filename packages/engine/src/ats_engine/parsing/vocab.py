"""Canonical vocabulary used by the deterministic tailoring-engine parser.

The old JD keyword extractor mixed a small tool list with terms found in a
candidate profile.  This module deliberately has no profile dependency: it is
only a description of vocabulary that can be observed in a job description.
Keeping aliases and spelling variants here also gives evidence resolution one
place to answer the much narrower question, "are these two wordings the same
skill?"
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Final


@dataclass(frozen=True, slots=True)
class VocabularyEntry:
    """A canonical, typed term that may appear in a job description.

    ``allow_short`` exists for the handful of punctuation-heavy programming
    tokens such as ``C#``.  It is intentionally false for ordinary one and
    two-character abbreviations: a bare ``C`` or ``B`` is never a requirement.
    """

    canonical: str
    aliases: tuple[str, ...]
    display: str
    kind: str
    category: str
    allow_short: bool = False


@dataclass(frozen=True, slots=True)
class VocabularyMatch:
    """One raw-text occurrence of a :class:`VocabularyEntry`."""

    entry: VocabularyEntry
    surface: str
    start: int
    end: int
    alias: str


# These are intentionally narrow spelling normalizations rather than an
# English stemmer.  A stemmer would collapse different career facts (for
# example, "model" and "modelling") far too aggressively for a truth-grounded
# product.
_SPELLING_VARIANTS: Final[tuple[tuple[str, str], ...]] = (
    ("modeling", "modelling"),
    ("visualization", "visualisation"),
    ("optimization", "optimisation"),
    ("organization", "organisation"),
    ("analyze", "analyse"),
    ("analyzing", "analysing"),
    ("analyzed", "analysed"),
    ("customization", "customisation"),
)


def normalize_term(text: str) -> str:
    """Return a conservative comparison key for a skill or requirement.

    The key is case-insensitive, whitespace/punctuation tolerant, and treats a
    small set of US/Canadian-English spelling variants as identical.  It is
    suitable for exact alias lookup, not for semantic similarity.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("’", "'")
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[‐‑‒–—―]", "-", normalized)
    for source, target in _SPELLING_VARIANTS:
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    # Treat separators as formatting differences.  Keep ``#`` because C# is a
    # distinct language, but otherwise discard punctuation that has no bearing
    # on a term's identity.
    normalized = re.sub(r"[./_-]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9#+]+", " ", normalized)
    return " ".join(normalized.split())


def _entry(
    canonical: str,
    *,
    aliases: tuple[str, ...] = (),
    display: str | None = None,
    kind: str = "tool",
    category: str,
    allow_short: bool = False,
) -> VocabularyEntry:
    all_aliases = tuple(dict.fromkeys((canonical, *aliases)))
    return VocabularyEntry(
        canonical=canonical,
        aliases=all_aliases,
        display=display or canonical,
        kind=kind,
        category=category,
        allow_short=allow_short,
    )


# Categories are deliberately limited to the public v2 taxonomy.  This table
# includes the legacy COMMON_TECH_TERMS as well as the BI/analytics terms that
# the old extractor missed.  Synonyms live on one canonical entry so a JD with
# both "data modeling" and "data modelling" produces one requirement.
VOCABULARY: Final[tuple[VocabularyEntry, ...]] = (
    # BI, analytics, and data engineering.
    _entry("power bi", aliases=("powerbi",), display="Power BI", category="bi_analytics"),
    _entry("power bi desktop", display="Power BI Desktop", category="bi_analytics"),
    _entry("power bi service", display="Power BI Service", category="bi_analytics"),
    _entry("power query", aliases=("m query", "power query editor"), display="Power Query", category="bi_analytics"),
    _entry("dax", display="DAX", category="bi_analytics"),
    _entry("star schema", aliases=("star-schema",), category="bi_analytics", kind="methodology"),
    _entry("dataflows", aliases=("dataflow", "data flows"), category="data_engineering"),
    _entry("refresh cycles", aliases=("data refresh", "refresh cycle"), category="bi_analytics", kind="methodology"),
    _entry("workspaces", aliases=("workspace",), category="bi_analytics"),
    _entry(
        "row-level security",
        aliases=("row level security", "rls"),
        display="row-level security",
        category="security_governance",
    ),
    _entry("excel", aliases=("microsoft excel",), display="Excel", category="productivity"),
    _entry("tableau", category="bi_analytics"),
    _entry("looker", category="bi_analytics"),
    _entry("amazon quicksight", aliases=("quicksight",), display="Amazon QuickSight", category="bi_analytics"),
    _entry("data visualization", aliases=("data visualisation",), category="bi_analytics", kind="skill"),
    _entry("dashboards", aliases=("dashboard",), category="bi_analytics", kind="skill"),
    _entry(
        "business intelligence",
        aliases=("bi",),
        display="business intelligence",
        category="bi_analytics",
        kind="domain",
    ),
    _entry("semantic models", aliases=("semantic model",), category="bi_analytics", kind="methodology"),
    _entry("data modelling", aliases=("data modeling",), category="bi_analytics", kind="methodology"),
    _entry("data warehousing", aliases=("data warehouse",), category="data_engineering", kind="methodology"),
    _entry("data integration", category="data_engineering", kind="skill"),
    _entry("data ingestion", category="data_engineering", kind="skill"),
    _entry("data pipelines", aliases=("data pipeline",), category="data_engineering", kind="skill"),
    _entry(
        "multi-source data pipelines",
        aliases=("multi source data pipelines", "multi-source data pipeline", "multi source data pipeline"),
        category="data_engineering",
        kind="skill",
    ),
    _entry("etl", aliases=("extract transform load",), display="ETL", category="data_engineering"),
    _entry("elt", aliases=("extract load transform",), display="ELT", category="data_engineering"),
    _entry("data quality", category="data_engineering", kind="methodology"),
    _entry("data integrity", category="data_engineering", kind="methodology"),
    _entry("data governance", category="security_governance", kind="methodology"),
    _entry("survey data", category="domain", kind="domain"),
    _entry("dbt", category="data_engineering"),
    _entry("snowflake", category="database"),
    _entry("redshift", category="database"),
    _entry("spark", aliases=("apache spark",), category="data_engineering"),
    _entry("airflow", aliases=("apache airflow",), category="data_engineering"),
    _entry("sql", aliases=("structured query language",), display="SQL", category="database"),
    _entry("postgresql", aliases=("postgres",), display="PostgreSQL", category="database"),
    _entry("mongodb", aliases=("mongo db", "mongo"), display="MongoDB", category="database"),
    _entry("machine learning", category="domain", kind="domain"),
    _entry("scikit-learn", aliases=("scikit learn",), display="scikit-learn", category="framework"),
    _entry("d3.js", aliases=("d3", "d3 js"), display="D3.js", category="framework"),
    # Geospatial and document-management terms from the COO case.
    _entry("esri arcgis", aliases=("esri", "arcgis", "esri arc gis"), display="ESRI ArcGIS", category="geospatial"),
    _entry("arcgis", aliases=("arc gis",), display="ArcGIS", category="geospatial"),
    _entry("qgis", display="QGIS", category="geospatial"),
    _entry("geocoding", aliases=("geo coding",), category="geospatial", kind="skill"),
    _entry("m-files", aliases=("m files", "mfiles"), display="M-Files", category="operations_support"),
    _entry("document management", aliases=("document-management",), category="operations_support", kind="skill"),
    _entry("sharepoint", aliases=("share point",), display="SharePoint", category="productivity"),
    _entry("ocap", display="OCAP", category="domain", kind="domain"),
    # Cloud, platform, and integration.
    _entry("azure", aliases=("microsoft azure",), display="Azure", category="cloud"),
    _entry("azure devops", aliases=("azure-devops",), display="Azure DevOps", category="platform"),
    _entry("terraform", display="Terraform", category="cloud"),
    _entry(
        "azure functions",
        aliases=("azure function apps", "azure function"),
        display="Azure Functions",
        category="cloud",
    ),
    _entry("azure api management", aliases=("api management",), display="Azure API Management", category="cloud"),
    _entry("aws", aliases=("amazon web services",), display="AWS", category="cloud"),
    _entry("gcp", aliases=("google cloud platform", "google cloud"), display="GCP", category="cloud"),
    _entry("docker", category="platform"),
    _entry("kubernetes", aliases=("k8s",), category="platform"),
    _entry("microservices", aliases=("microservice",), category="platform", kind="methodology"),
    _entry(
        "rest apis", aliases=("rest api", "restful api", "restful apis"), display="REST APIs", category="integration"
    ),
    _entry("graphql", category="integration"),
    _entry("system integration", aliases=("system integrations",), category="integration", kind="skill"),
    _entry("custom apis", aliases=("custom api",), category="integration"),
    _entry("power platform", aliases=("microsoft power platform",), display="Power Platform", category="platform"),
    _entry("power apps", aliases=("powerapps",), display="Power Apps", category="platform"),
    _entry("power automate", aliases=("powerautomate",), display="Power Automate", category="platform"),
    _entry("power pages", aliases=("powerpages",), display="Power Pages", category="platform"),
    _entry("dataverse", aliases=("common data service",), display="Dataverse", category="database"),
    _entry(
        "model-driven apps", aliases=("model driven apps", "model-driven app", "model driven app"), category="platform"
    ),
    _entry("pcf controls", aliases=("pcf control", "pcf"), display="PCF controls", category="framework"),
    _entry("dynamics 365", aliases=("dynamics",), display="Dynamics 365", category="platform"),
    _entry("salesforce", category="platform"),
    _entry("hubspot", category="platform"),
    _entry("openai", aliases=("open ai",), display="OpenAI", category="platform"),
    _entry("gemini", aliases=("google gemini",), category="platform"),
    _entry("rag", aliases=("retrieval augmented generation",), display="RAG", category="framework"),
    _entry("llm", aliases=("large language model", "large language models"), display="LLM", category="framework"),
    # Security, support, and quality.
    _entry("cybersecurity", aliases=("cyber security",), category="security_governance", kind="domain"),
    _entry("access controls", aliases=("access control",), category="security_governance", kind="methodology"),
    _entry("audit logging", aliases=("audit logs", "audit log"), category="security_governance", kind="methodology"),
    _entry("version control", aliases=("source control",), category="source_control", kind="skill"),
    _entry("branching and merging", aliases=("branching", "merging"), category="source_control", kind="skill"),
    _entry(
        "ci/cd",
        aliases=("cicd", "continuous integration", "continuous delivery"),
        display="CI/CD",
        category="testing_quality",
    ),
    _entry("troubleshooting", aliases=("trouble shooting",), category="operations_support", kind="skill"),
    _entry(
        "it support",
        aliases=("information technology support",),
        display="IT support",
        category="operations_support",
        kind="skill",
    ),
    _entry("application support", category="operations_support", kind="skill"),
    _entry("production support", category="operations_support", kind="skill"),
    _entry("systems administration", aliases=("system administration",), category="operations_support", kind="skill"),
    _entry("root cause analysis", aliases=("root-cause analysis",), category="operations_support", kind="methodology"),
    _entry("debugging", category="operations_support", kind="skill"),
    _entry("defect resolution", category="testing_quality", kind="skill"),
    _entry("unit testing", aliases=("unit tests",), category="testing_quality", kind="skill"),
    _entry("integration testing", aliases=("integration tests",), category="testing_quality", kind="skill"),
    _entry("api testing", category="testing_quality", kind="skill"),
    _entry(
        "test automation", aliases=("automated testing", "automated tests"), category="testing_quality", kind="skill"
    ),
    _entry("regression testing", category="testing_quality", kind="skill"),
    _entry("test cases", aliases=("test case",), category="testing_quality", kind="skill"),
    _entry("test coverage", category="testing_quality", kind="methodology"),
    _entry(
        "test-driven development",
        aliases=("tdd",),
        display="test-driven development",
        category="testing_quality",
        kind="methodology",
    ),
    _entry("quality assurance", aliases=("qa",), category="testing_quality", kind="skill"),
    _entry("quality engineering", category="testing_quality", kind="skill"),
    _entry("software testing", category="testing_quality", kind="skill"),
    _entry("software quality", category="testing_quality", kind="skill"),
    _entry("code review", aliases=("code reviews",), category="testing_quality", kind="skill"),
    _entry("selenium", category="testing_quality"),
    _entry("cypress", category="testing_quality"),
    _entry("playwright", category="testing_quality"),
    _entry("junit", category="testing_quality"),
    _entry("mockito", category="testing_quality"),
    _entry("jest", category="testing_quality"),
    _entry("pytest", category="testing_quality"),
    _entry("performance testing", category="testing_quality", kind="skill"),
    _entry("load testing", category="testing_quality", kind="skill"),
    _entry("security testing", category="testing_quality", kind="skill"),
    # Programming, frameworks, and web development.
    _entry("python", category="programming_language"),
    _entry("rust", category="programming_language"),
    _entry("java", category="programming_language"),
    _entry("javascript", category="programming_language"),
    _entry("typescript", category="programming_language"),
    _entry("c#", aliases=("c sharp",), display="C#", category="programming_language", allow_short=True),
    _entry(".net", aliases=("dotnet", "dot net"), display=".NET", category="framework", allow_short=True),
    _entry(".net framework", aliases=("dotnet framework",), display=".NET Framework", category="framework"),
    _entry("powershell", aliases=("power shell",), display="PowerShell", category="programming_language"),
    _entry("liquid", category="programming_language"),
    _entry("react", category="framework"),
    _entry("react native", aliases=("react-native",), category="framework"),
    _entry("node.js", aliases=("node js", "nodejs"), display="Node.js", category="framework"),
    _entry("express", aliases=("express.js", "express js"), display="Express", category="framework"),
    _entry("next.js", aliases=("next js", "nextjs"), display="Next.js", category="framework"),
    _entry("angular", category="framework"),
    _entry("vue", aliases=("vue.js", "vue js"), display="Vue", category="framework"),
    _entry("spring", aliases=("spring framework",), category="framework"),
    _entry("hibernate", category="framework"),
    _entry("fastapi", aliases=("fast api",), display="FastAPI", category="framework"),
    _entry("html5", aliases=("html",), display="HTML5", category="web_development"),
    _entry("css", aliases=("css3",), display="CSS", category="web_development"),
    _entry("web development", category="web_development", kind="skill"),
    _entry("frontend", aliases=("front-end", "front end"), category="web_development", kind="skill"),
    _entry("backend", aliases=("back-end", "back end"), category="web_development", kind="skill"),
    _entry("full-stack", aliases=("full stack", "fullstack"), category="web_development", kind="skill"),
    _entry("plug-ins", aliases=("plug-in", "plugins", "plugin"), category="framework"),
    # Business analysis, documentation, and productivity.
    _entry("business requirements", category="business_analysis", kind="skill"),
    _entry("user experience", aliases=("ux",), display="user experience", category="business_analysis", kind="skill"),
    _entry("user interface design", aliases=("ui design",), category="business_analysis", kind="skill"),
    _entry("information architecture", category="business_analysis", kind="skill"),
    _entry("technical documentation", aliases=("technical documents",), category="documentation", kind="skill"),
    _entry("knowledge transfer", category="documentation", kind="skill"),
    _entry(
        "communication",
        aliases=("written communication", "verbal communication"),
        category="communication",
        kind="soft",
    ),
    _entry("stakeholder communication", category="communication", kind="soft"),
    _entry("collaboration", aliases=("cross-functional collaboration",), category="communication", kind="soft"),
)


_CANONICAL_INDEX: Final[dict[str, VocabularyEntry]] = {normalize_term(entry.canonical): entry for entry in VOCABULARY}
_ALIAS_INDEX: Final[dict[str, VocabularyEntry]] = {
    normalize_term(alias): entry for entry in VOCABULARY for alias in entry.aliases
}


def vocabulary_entry(canonical_or_alias: str) -> VocabularyEntry | None:
    """Look up an entry by canonical form or a known spelling/alias."""

    key = normalize_term(canonical_or_alias)
    return _CANONICAL_INDEX.get(key) or _ALIAS_INDEX.get(key)


def aliases_for(canonical_or_alias: str) -> tuple[str, ...]:
    """Return all source-matchable aliases for a known canonical term."""

    entry = vocabulary_entry(canonical_or_alias)
    return entry.aliases if entry is not None else ()


def is_admissible_entry(entry: VocabularyEntry) -> bool:
    """Whether an entry may be emitted as a standalone JD requirement."""

    normalized = normalize_term(entry.canonical)
    compact_length = len(re.sub(r"[^a-z0-9]", "", normalized))
    return compact_length > 2 or entry.allow_short


def _is_admissible_alias(alias: str, entry: VocabularyEntry) -> bool:
    compact_length = len(re.sub(r"[^a-z0-9]", "", normalize_term(alias)))
    return compact_length > 2 or entry.allow_short


@lru_cache(maxsize=1024)
def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Compile a boundary-aware, formatting-tolerant alias matcher."""

    # A separator in a product name is generally formatting, so "M-Files",
    # "M Files", and "M/Files" match one alias.  ``#`` is intentionally not
    # a separator because C# must not match a bare C.
    parts: list[str] = []
    previous_was_separator = False
    for character in alias.casefold():
        if character.isspace() or character in "-_. /":
            if not previous_was_separator:
                parts.append(r"[\s._/-]+")
            previous_was_separator = True
            continue
        parts.append(re.escape(character))
        previous_was_separator = False
    escaped = "".join(parts)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", flags=re.IGNORECASE)


def find_vocabulary_matches(text: str) -> list[VocabularyMatch]:
    """Find all vocabulary occurrences in *text*, retaining exact surfaces.

    Matches are returned in source order, with longer overlapping occurrences
    first.  Consumers that need phrase-first extraction can therefore select
    non-overlapping matches greedily without reimplementing matching rules.
    """

    matches: list[VocabularyMatch] = []
    seen: set[tuple[str, int, int]] = set()
    for entry in VOCABULARY:
        if not is_admissible_entry(entry):
            continue
        for alias in entry.aliases:
            if not _is_admissible_alias(alias, entry):
                continue
            for found in _alias_pattern(alias).finditer(text):
                key = (entry.canonical, found.start(), found.end())
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    VocabularyMatch(
                        entry=entry,
                        surface=found.group(0),
                        start=found.start(),
                        end=found.end(),
                        alias=alias,
                    )
                )
    return sorted(matches, key=lambda match: (match.start, -(match.end - match.start), match.entry.canonical))


# Certification inference is deliberately one-way and narrowly scoped.  It
# lets a certified candidate surface an exact skill only with the certification
# named; it never turns a broad cloud credential into Azure DevOps experience.
CERTIFICATION_IMPLICATIONS: Final[dict[str, tuple[str, ...]]] = {
    "PL-300": ("power bi desktop", "dax", "power query", "data modelling", "power bi service"),
    "PL-400": ("power platform", "power apps", "power automate", "dataverse"),
    "AZ-900": ("azure",),
}

_CERTIFICATE_NAME_CODES: Final[tuple[tuple[str, str], ...]] = (
    ("power bi data analyst associate", "PL-300"),
    ("power platform developer associate", "PL-400"),
    ("azure fundamentals", "AZ-900"),
)


def certification_codes(certification: object) -> tuple[str, ...]:
    """Return known certification codes from a string or certification object."""

    if isinstance(certification, str):
        source = certification
    else:
        name = getattr(certification, "name", "")
        credential_id = getattr(certification, "credential_id", "")
        source = f"{name} {credential_id}"
    upper = source.upper()
    found = [f"{prefix}-{number}" for prefix, number in re.findall(r"\b(PL|AZ)[ -]?(\d{3})\b", upper)]
    lowered = source.casefold()
    for name_fragment, code in _CERTIFICATE_NAME_CODES:
        if name_fragment in lowered and code not in found:
            found.append(code)
    return tuple(found)


def certification_implications(certification: object) -> tuple[str, ...]:
    """Return canonical terms safely implied by a known certification.

    ``AZ-900`` intentionally returns only ``azure``.  In particular it does
    not imply Azure DevOps, deployment experience, or any other product.
    """

    terms: list[str] = []
    for code in certification_codes(certification):
        for term in CERTIFICATION_IMPLICATIONS.get(code, ()):
            if term not in terms:
                terms.append(term)
    return tuple(terms)


__all__ = [
    "CERTIFICATION_IMPLICATIONS",
    "VOCABULARY",
    "VocabularyEntry",
    "VocabularyMatch",
    "aliases_for",
    "certification_codes",
    "certification_implications",
    "find_vocabulary_matches",
    "is_admissible_entry",
    "normalize_term",
    "vocabulary_entry",
]
