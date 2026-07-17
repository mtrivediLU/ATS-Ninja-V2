from __future__ import annotations

from ats_engine.generation.document_normalization import normalize_document_text


def test_normalization_repairs_only_mechanical_line_break_artifacts() -> None:
    assert normalize_document_text("data warehous-, ing") == "data warehousing"
    assert normalize_document_text("microser- vices") == "microservices"
    assert normalize_document_text("Hello\u00ad\x00 world") == "Hello world"


def test_normalization_preserves_supported_hyphens_and_facts() -> None:
    source = "real-time offline-first service-to-service multi-language 99% 2024 Acme Corp"
    assert normalize_document_text(source) == source
    assert normalize_document_text("service- to-service") == "service- to-service"
