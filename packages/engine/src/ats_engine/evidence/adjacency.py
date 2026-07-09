from __future__ import annotations

"""Generic tool-category clusters used to build honest adjacency phrasing.

This is candidate-agnostic: it only says which tools sit in the same functional
category (data warehouse, orchestration, BI, etc). The evidence engine pairs a
JD's missing tool with whatever real tool the candidate's own profile shows in
the same category, so the phrasing is always grounded in something the candidate
actually did, never invented.
"""

TOOL_CATEGORIES: dict[str, dict[str, object]] = {
    "cloud_data_warehouse": {
        "label": "cloud data warehouse design and dimensional modeling",
        "tools": [
            "snowflake",
            "bigquery",
            "redshift",
            "postgresql",
            "mysql",
            "sql server",
            "azure synapse",
            "synapse",
            "databricks sql",
            "oracle",
            "teradata",
        ],
    },
    "orchestration": {
        "label": "pipeline orchestration and scheduled ETL",
        "tools": [
            "airflow",
            "prefect",
            "dagster",
            "dbt",
            "azure data factory",
            "luigi",
            "aws glue",
            "glue",
            "informatica",
            "ssis",
        ],
    },
    "big_data_processing": {
        "label": "large-scale data processing",
        "tools": ["spark", "databricks", "hadoop", "flink", "emr"],
    },
    "streaming": {
        "label": "real-time event streaming and data delivery",
        "tools": ["kafka", "kinesis", "pubsub", "event hubs", "rabbitmq"],
    },
    "bi_tool": {
        "label": "BI platforms and executive reporting",
        "tools": [
            "tableau",
            "power bi",
            "amazon quicksight",
            "quicksight",
            "d3.js",
            "d3",
            "looker",
            "qlik",
            "sigma",
            "metabase",
            "looker studio",
            "business intelligence",
            "data visualization",
            "dashboards",
            "dashboard",
            "semantic models",
            "dataflow",
        ],
    },
    "cloud_provider": {
        "label": "cloud platform experience",
        "tools": ["aws", "amazon web services", "azure", "gcp", "google cloud"],
    },
    "container_orchestration": {
        "label": "containerized deployment",
        "tools": ["kubernetes", "docker swarm", "ecs", "docker", "openshift"],
    },
    "llm_framework": {
        "label": "LLM integration and document Q&A / retrieval patterns",
        "tools": [
            "langchain",
            "llamaindex",
            "rag",
            "retrieval augmented generation",
            "vector database",
            "pinecone",
            "weaviate",
            "chroma",
            "openai api",
            "gemini api",
            "azure openai",
        ],
    },
    "backend_framework": {
        "label": "backend service development",
        "tools": [
            "django",
            "flask",
            "fastapi",
            "spring",
            "spring boot",
            "express",
            "nestjs",
            ".net",
            "c#",
            "asp.net",
            "hibernate",
        ],
    },
    "rpa": {
        "label": "RPA and low-code workflow automation",
        "tools": [
            "uipath",
            "blue prism",
            "automation anywhere",
            "power automate",
            "power apps",
        ],
    },
    "frontend_framework": {
        "label": "modern frontend development",
        "tools": ["react", "angular", "vue", "vue.js", "next.js", "svelte", "react native"],
    },
    "api_style": {
        "label": "API design",
        "tools": ["rest", "rest apis", "graphql", "grpc", "soap"],
    },
    "crm_platform": {
        "label": "CRM platform work",
        "tools": ["salesforce", "hubspot", "dynamics 365", "zoho"],
    },
    "ci_cd": {
        "label": "CI/CD and release automation",
        "tools": ["jenkins", "github actions", "gitlab ci", "circleci", "azure devops", "travis"],
    },
    "ml_framework": {
        "label": "applied machine learning",
        "tools": [
            "scikit-learn",
            "tensorflow",
            "pytorch",
            "keras",
            "random forest",
            "xgboost",
            "ml pipelines",
        ],
    },
    "iac": {
        "label": "infrastructure as code",
        "tools": ["terraform", "cloudformation", "pulumi", "ansible"],
    },
}


def find_category(keyword: str) -> tuple[str, str, list[str]] | None:
    """Return (category_key, label, tools) for the category containing keyword, if any."""
    normalized = keyword.lower().strip()
    for category, data in TOOL_CATEGORIES.items():
        tools = data["tools"]
        if isinstance(tools, list) and normalized in tools:
            return category, str(data["label"]), list(tools)
    return None


def category_tools(category: str) -> list[str]:
    data = TOOL_CATEGORIES.get(category)
    if not data:
        return []
    tools = data["tools"]
    return list(tools) if isinstance(tools, list) else []
