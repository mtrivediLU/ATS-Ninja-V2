from __future__ import annotations

import pytest

from ats_engine.models import ContactInfo, Experience, Profile
from ats_engine.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# Synthetic, non-personal fixtures.
#
# The legacy suite embedded a real candidate's resume (name, employers,
# certifications). That is candidate PII and was deliberately NOT migrated. The
# fixtures below are entirely fictional but exercise the same behaviors:
# multiple employers, skills tiered across bullets/summary/listed-only,
# education, certifications, PDF line wrapping, and scale claims.
# ---------------------------------------------------------------------------


def sample_profile() -> Profile:
    """A synthetic profile used to exercise the generic tiering/validation logic."""
    return Profile(
        contact=ContactInfo(name="Jordan Rivera", email="jordan@example.com"),
        retired_emails=["old@example.com"],
        role_identities=["Software Engineer"],
        tier_a={"python": "Python", "sql": "SQL", "azure": "Azure"},
        tier_b={"power bi": "Power BI", "data visualization": "data visualization"},
        tier_c={"fastapi": "FastAPI", "graphql": "GraphQL"},
        adjacency={},
        experiences=[
            Experience(
                company="Acme Corp",
                title="Software Engineer",
                location="Remote",
                dates="2020 to 2023",
                bullets=["Built Python pipelines.", "Reduced processing time by 40%."],
            )
        ],
        education=[],
        certifications=[],
        supported_metrics=["40%", "5 hours to minutes"],
    )


@pytest.fixture
def profile() -> Profile:
    return sample_profile()


# A synthetic multi-employer resume that mirrors the shape of the legacy
# regression fixture (six roles, tiered skills, education, certifications,
# wrapped bullet lines, scale claims) without any real person's data.
SYNTHETIC_RESUME = """
Alex Morgan
Senior Software Engineer | Full-Stack, Data & AI Solutions
Springfield, Ontario, Canada
PROFESSIONAL SUMMARY
Senior Software Engineer with 8+ years designing production systems, data engineering, BI, and AI/ML applications.
TECHNICAL SKILLS
Languages: Python, Java, JavaScript, SQL, C, C++, PHP, HTML5, CSS3.
Frontend: React, React Native, Next.js, Angular, Vue.js, Bootstrap, Tailwind.
Backend & APIs: Java Spring MVC, Hibernate, Node.js, RESTful APIs, Microservices, SaaS.
Databases & Data Engineering: PostgreSQL, MS SQL Server, SSIS, SSRS, dbt, ETL/ELT Pipelines, Data Warehousing, Data Modeling, Data Governance.
BI & Analytics: Tableau, Power BI, Power Apps, Power Automate, ArcGIS, QGIS.
Cloud & DevOps: Microsoft Azure, AWS, Google Cloud, Linux, Docker, Kubernetes, CI/CD, Git.
AI & Machine Learning: OpenAI & Gemini APIs, LLM Integration, Predictive Modeling, ML Pipelines, Random Forest.
Enterprise Platforms: Salesforce, HubSpot, SAP Commerce Cloud.
Methodologies & Tools: Agile/Scrum, Waterfall, SDLC, Requirements Gathering, System Integration, Jira, Confluence.
PROFESSIONAL EXPERIENCE
Northwind Medical Toronto, ON (Remote)
Business Intelligence Developer Oct 2024 - Apr 2026
- Enterprise Data Warehouse: Architected and built a centralized data warehouse using PostgreSQL and dbt, creating a unified source of truth across Finance, QA, Production, and HR.
- ETL/ELT Pipelines: Designed and maintained pipelines ingesting device logs alongside Salesforce and HubSpot into a reliable analytics layer.
- Predictive Analytics & Reporting: Developed predictive inventory models and automated Tableau dashboards, reducing manual reporting overhead by 40%.
Ridgeline Labs Springfield, ON
Software Development Consultant Jun 2024 - Jul 2025
- End-to-End Ownership: Designed, built, and deployed the Ridgeline Safe and Smart Operations Data Platform end-to-end.
- Real-Time Architecture: Developed AI-assisted dashboards and automated reporting systems for field environments.
City of Springfield Springfield, ON
Business Intelligence Analyst May 2024 - Aug 2024
- Systems Integration: Integrated third-party vendor applications with SQL Server using SSIS, Python, and Google Cloud SQL Auth Proxy.
- BI & Data Governance: Built Service-Based Budgeting systems using SQL and Power BI; trained end-users on data-governance standards.
Vertex Software Springfield, ON
Lead Software Developer Oct 2023 - May 2024
- Offline-First Mobile Architecture: Architected a React Native application enabling field data collection and automated reporting.
- Process Automation: Automated safety inspection forms using Power Automate, reducing engineer reporting time from 5 hours to minutes.
Prairie Research Centre Springfield, ON
Research Associate (Data & ML) Mar 2022 - Jul 2023
- Applied Machine Learning: Developed ML models using Random Forest, achieving a 99.5% F1 score.
- Spatial Data Analysis: Processed geospatial datasets using ArcGIS and QGIS.
Global Systems Consulting Metro City, Country
Lead Software Engineer Nov 2017 - Oct 2021
- Technical Leadership: Led a team of four engineers maintaining a high-traffic B2C e-commerce platform serving millions of users.
- Global Deployments: Launched 13 B2B e-commerce platforms across Europe and North America on SAP Commerce Cloud.
- CI/CD & Reliability: Optimized deployment workflows, maintaining 100% uptime for critical production services.
EDUCATION
Springfield University Springfield, ON
Master of Computational Science (Thesis: ML for Geological Discovery) 2021 - 2023
Metro Technological University Country
Bachelor of Computer Engineering (GPA: 3.3/4.0) 2013 - 2017
CERTIFICATIONS
Certified AI Specialist (AI-201) 2025
Cloud Certified: Fundamentals (AZ-900) 2024
BI Certified: Data Analyst Associate (PL-300) 2024
Platform Certified: Developer Associate (PL-400) 2024
"""

SYNTHETIC_JD = """
BI Developer - Fixed Term Contract
Vantage Global Industries
1500 Market Street, Toronto, ON M3B 3L1
Your day to day
Design, develop, deploy, and maintain BI reporting suites, including dataflow, semantic models, frontend reports, dashboards, and BI solutions.
Source, prepare, and integrate data for analysis from diverse business and operational processes.
What we are looking for
Proficiency in data visualization tools such as MSFT Power BI, Amazon QuickSight, or open-source frameworks like D3.js.
Solid understanding of business intelligence concepts and tools, including SQL, ETL processes, and data warehousing.
Experience with data warehousing solutions based on Snowflake, AWS Redshift, or open-source databases like PostgreSQL.
Experience with data modeling and data integration techniques to ensure data quality.
Ability to design and implement dashboards and reports that meet business requirements.
Knowledge of DAX queries and SQL-like programming.
Preferred Qualifications:
Certification in relevant technologies such as a Data Analyst Associate or equivalent.
Knowledge of DAX, Python and JavaScript.
Familiarity with machine learning and predictive analytics.
"""

# A short synthetic JD used by lighter-weight pipeline tests.
BASIC_JD = (
    "Job Title: AI Engineer\n"
    "Company: Northstar Analytics\n"
    "Location: Toronto, Ontario hybrid\n"
    "Required qualifications:\n"
    "- Python for production data and AI systems\n"
    "- SQL and data warehouse experience\n"
    "- LLM integration, prompt engineering, and retrieval workflows\n"
    "- ETL pipelines and stakeholder communication\n"
    "Preferred qualifications:\n"
    "- Azure, Docker, Tableau, Power BI, and Java microservices\n"
    "Responsibilities:\n"
    "- Build internal AI assistants for documents and operational data.\n"
    "- Develop analytics pipelines and reporting for business teams.\n"
    "- Work with engineering and business stakeholders in a regulated environment.\n"
    "This role supports healthcare data operations and requires clear documentation. "
    "The team uses Python, SQL, LLMs, Azure, Docker, Tableau, and ETL patterns."
)

# A resume with hard-wrapped PDF-style lines and scale claims, kept short.
WRAPPED_RESUME_TEXT = (
    "Jordan Rivera\n"
    "555-201-3344 | jordan.rivera@oldschool.edu | linkedin.com/in/jordanrivera\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Analytics Toronto, ON\n"
    "Senior Data Engineer Jan 2020 - Mar 2024\n"
    "- Architected and built a centralized data warehouse using PostgreSQL, creating a\n"
    "unified source of truth serving millions of users across the platform.\n"
    "- Optimized deployment workflows, maintaining 100% uptime for critical\n"
    "production services and reducing release time by 40%.\n"
    "Beta Retail Group Ottawa, ON\n"
    "Data Analyst Jun 2016 - Dec 2019\n"
    "- Built SQL reporting for a team of 12 analysts.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2012 - 2016\n"
)


class ScriptedProvider(LLMProvider):
    """A test double implementing the LLMProvider Protocol.

    Returns a fixed completion for every prompt. Used to prove the engine
    accepts any provider adapter and still validates its output, without any
    real vendor SDK or network call.
    """

    def __init__(self, response: str, *, identity: str = "scripted") -> None:
        self._response = response
        self._identity = identity
        self.calls: list[str] = []

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


# ---------------------------------------------------------------------------
# Phase 2A adversarial fixtures.
#
# A synthetic candidate with a *tightly controlled* evidence set, so the
# adversarial anti-fabrication suite can inject claims the candidate provably
# never made and assert they never reach the final ApplicationKit.
#   - real employer: Northstar Analytics (NOT Google)
#   - real title: Data Analyst (NOT Director/Chief anything)
#   - real skills: Python, SQL, dashboards (NOT Rust)
#   - real degree: Bachelor of Computer Science (NOT PhD)
#   - real metric: 30% (so a real metric can be shown to survive)
#   - real tenure: 2022-2024 (~2 years, so "10 years" is provably false)
#   - no certifications, no team-size/headcount evidence
# ---------------------------------------------------------------------------
ADVERSARIAL_RESUME = (
    "Jordan Rivera\n"
    "jordan.rivera@example.com | linkedin.com/in/jordanrivera\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Northstar Analytics Toronto, ON\n"
    "Data Analyst 2022 - 2024\n"
    "- Built dashboards and SQL reporting using Python, reducing manual reporting time by 30%.\n"
    "- Prepared data pipelines and documentation for business analysts.\n"
    "EDUCATION\n"
    "Carleton University Ottawa, ON\n"
    "Bachelor of Computer Science 2018 - 2022\n"
)

ADVERSARIAL_JD = (
    "Job Title: AI Engineer\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Python and SQL for data systems\n"
    "- Dashboards and reporting for business teams\n"
    "The team uses Python and SQL."
)

# Generic, truthful, style-clean padding used to bulk an injected answer up to
# the engine's minimum answer length without adding any new candidate claim, so
# only the fabricated sentence is the thing under test.
CLEAN_ANSWER_PADDING = (
    "I care about clear communication and steady delivery on the work I take on. "
    "I document what I build so the next person can maintain it without guesswork. "
    "I keep scope honest and ship the smallest useful version first. "
    "I collaborate closely with the people who rely on the output."
)


def fabricated_answer(claim_sentence: str) -> str:
    """A first-person answer whose only fabrication is ``claim_sentence``.

    The clean padding keeps the answer long enough to pass the engine's answer
    length gate and lets a test assert that the truthful remainder survives while
    only the fabricated sentence is removed.
    """
    return f"{claim_sentence} {CLEAN_ANSWER_PADDING}"


class FabricatingProvider(LLMProvider):
    """A prompt-aware adversarial provider.

    It returns fabricated prose only for the artifact surface under test
    (answers, cover letter, or summary), and an empty string everywhere else so
    those steps fall back to the deterministic path. This routes a specific
    fabrication into a specific artifact while keeping the rest of the kit clean,
    so the assertion isolates the grounding gate.
    """

    def __init__(
        self,
        *,
        answer: str | None = None,
        cover: str | None = None,
        summary: str | None = None,
        identity: str | None = None,
    ) -> None:
        self._answer = answer
        self._cover = cover
        self._summary = summary
        # Identity is part of the engine's content-hash cache key. A fake provider
        # that returns different content must therefore advertise a different
        # identity, or the disk cache would serve one fabrication for another. A
        # real provider's identity already encodes its model/params, so this is
        # simply the correct behavior for a test double.
        import hashlib

        digest = hashlib.sha256(f"{answer}|{cover}|{summary}".encode()).hexdigest()[:12]
        self._identity = identity or f"fabricator:{digest}"
        self.calls: list[str] = []

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        lowered = prompt.lower()
        if self._answer is not None and "application question" in lowered:
            return self._answer
        if self._cover is not None and "cover letter body" in lowered:
            return self._cover
        if self._summary is not None and "resume summary" in lowered:
            return self._summary
        return ""
