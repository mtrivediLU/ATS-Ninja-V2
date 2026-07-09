# ADR-0002 — Replace scikit-learn TF-IDF with a dependency-light deterministic extractor

- Status: Accepted
- Date: 2026-07-09
- Phase: 0

## Context

Legacy `core/ats_scorer.py` extracted JD keywords with scikit-learn's
`TfidfVectorizer`, fit on a **single document** (`[text]`). scikit-learn pulls in
numpy and scipy — a heavy scientific stack — which is at odds with the engine's
goals of low operational cost, portability, and minimal dependency weight.

Critically, on a single document TF-IDF is **degenerate**: the inverse-document
frequency term is identical for every word (there is only one document), so the
TF-IDF ranking reduces exactly to a term-frequency ranking. The heavy dependency
buys nothing over counting.

## Decision

Re-implement `extract_keywords` / `calculate_ats_score` as a pure-Python,
frequency-based extractor with the same public API and behavior: the same token
shape, stopword filtering (a self-contained English list plus recruiting
boilerplate), and top-N selection, with alphabetical tie-breaking for
determinism. Remove scikit-learn (and its numpy/scipy transitive weight) from the
engine entirely.

## Consequences

- Far lighter, faster-to-install, more portable engine; smaller container images.
- Deterministic, explainable output (ties broken alphabetically).
- This is a deliberate rewrite of proven legacy logic, justified by a concrete
  reason (degenerate TF-IDF + heavy dependency), per the migration rules.
- If true multi-document IDF is ever needed (e.g. scoring against a corpus of
  postings), it can be added behind the same interface without reintroducing a
  heavyweight dependency for the single-document case.
