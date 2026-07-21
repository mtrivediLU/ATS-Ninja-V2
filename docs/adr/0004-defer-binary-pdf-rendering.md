# ADR-0004 — Defer binary PDF rendering; ship LaTeX artifacts in Phase 0

- Status: Accepted; exit condition exercised by [ADR-0018](0018-local-pdf-rendering.md)
- Date: 2026-07-09
- Phase: 0

> **2026-07-20 update:** the "revisit when server-side PDF output is a
> concrete product requirement" condition below was met — see ADR-0018. The
> engine-purity decision in this ADR still stands exactly as written: binary
> PDF rendering (WeasyPrint) lives only in `apps/api`, never in
> `packages/engine`.

## Context

Legacy `core/pdf_generator.py` rendered resumes/cover letters to PDF using
WeasyPrint and ReportLab. WeasyPrint depends on native libraries (cairo, pango,
gdk-pixbuf); ReportLab is a large pure-Python package. These are heavy for a
domain engine whose goals include portability and low operational cost, and PDF
rasterization is an **output-format** concern rather than career intelligence.

The engine already produces complete, Overleaf-ready **LaTeX** artifacts
(`resume_latex`, `cover_letter_latex`) deterministically, using only Jinja2.

## Decision

Migrate the LaTeX generation (deterministic, Jinja2-only) as the Phase 0
downloadable-artifact format. **Defer** binary PDF rasterization: do not migrate
WeasyPrint/ReportLab into the engine now. Revisit when server-side PDF output is
a concrete product requirement, at which point it belongs behind an explicit
rendering interface (and likely as an optional extra or a dedicated worker step),
not as a core engine dependency.

## Consequences

- The engine stays dependency-light and portable; container images stay small.
- Phase 0 still delivers a real, downloadable artifact (LaTeX / Overleaf).
- No fake "PDF download" capability is advertised before it exists.
- When PDF is needed, the rendering interface can choose WeasyPrint, a LaTeX
  toolchain, or a hosted service without touching domain logic.
