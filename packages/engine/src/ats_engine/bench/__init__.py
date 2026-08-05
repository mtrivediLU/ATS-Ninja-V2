"""Deterministic fixture benchmark for proposal-level tailoring diagnostics."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ats_engine.generation.diagnostics import RunDiagnostics
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.kit.contract import OptimizationTrace
from ats_engine.models import Mode
from ats_engine.pramana.scoring import score_resume


@dataclass(frozen=True, slots=True)
class ExternalScores:
    """Historical, externally measured ATS figures for calibration only."""

    provider: str
    base: float
    ats_ninja: float
    manual: float | None = None

    @property
    def manual_gap_closure(self) -> float | None:
        if self.manual is None or self.manual == self.base:
            return None
        return (self.ats_ninja - self.base) / (self.manual - self.base)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """A qualified fixture directory and its shared source-resume input."""

    name: str
    directory: Path
    source_resume: Path
    job_description: Path


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Stable measurements from one deterministic fixture run."""

    name: str
    pramana_before: float
    pramana_after: float
    score_path: tuple[float, ...]
    diagnostics: RunDiagnostics
    source_sha256: str
    delivered_sha256: str
    external_scores: ExternalScores | None


def fixture_root() -> Path:
    """Return the repository fixture corpus without depending on the CWD."""
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "real_extraction"


def discover_cases(root: Path | None = None) -> tuple[BenchmarkCase, ...]:
    """Discover qualified cases without baking fixture names into the harness."""
    resolved_root = root or fixture_root()
    shared_source = resolved_root / "candidate_resume.pymupdf.txt"
    cases: list[BenchmarkCase] = []
    for directory in sorted(path for path in resolved_root.iterdir() if path.is_dir()):
        job_description = directory / "job_description.txt"
        historical_output = directory / "resume_ats_ninja.pymupdf.txt"
        if not job_description.is_file() or not historical_output.is_file():
            continue
        # The real corpus intentionally keeps one candidate source outside the
        # case directories and stores historical ATS-Ninja output per case.
        # A self-contained future fixture can omit the shared source.
        source = shared_source if shared_source.is_file() else historical_output
        cases.append(
            BenchmarkCase(
                name=directory.name,
                directory=directory,
                source_resume=source,
                job_description=job_description,
            )
        )
    return tuple(cases)


def load_external_scores(directory: Path) -> ExternalScores | None:
    """Read optional historical external scores using only the stdlib TOML parser."""
    path = directory / "external_scores.toml"
    if not path.is_file():
        return None
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return ExternalScores(
        provider=str(raw["provider"]),
        base=float(raw["base"]),
        ats_ninja=float(raw["ats_ninja"]),
        manual=float(raw["manual"]) if "manual" in raw else None,
    )


def run_case(case: BenchmarkCase) -> BenchmarkResult:
    """Run one fixture through the deterministic pipeline and measure its output."""
    source = case.source_resume.read_text(encoding="utf-8")
    jd = case.job_description.read_text(encoding="utf-8")
    result = run_pipeline(
        resume_text=source,
        job_description=jd,
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    trace_raw = result.metadata.get("optimization_trace")
    if not isinstance(trace_raw, OptimizationTrace):
        raise AssertionError("tailoring v2 must publish proposal diagnostics")
    diagnostics = trace_raw.diagnostics
    if result.resume_plan is None:
        raise AssertionError("benchmark requires a generated resume plan")
    plan = result.resume_plan
    return BenchmarkResult(
        name=case.name,
        pramana_before=score_resume(
            source,
            plan.requirements,
            plan.evidence_links,
            jd_title=plan.jd_profile.title,
        ).score,
        pramana_after=score_resume(
            result.resume_text,
            plan.requirements,
            plan.evidence_links,
            source_resume_text=source,
            tailored=True,
            placements=plan.placement_actions,
            jd_title=plan.jd_profile.title,
        ).score,
        score_path=tuple(trace_raw.score_path),
        diagnostics=diagnostics,
        source_sha256=diagnostics.source_projection_sha256,
        delivered_sha256=diagnostics.delivered_sha256,
        external_scores=load_external_scores(case.directory),
    )


def run_all(root: Path | None = None) -> tuple[BenchmarkResult, ...]:
    """Run all discovered fixtures in lexical order."""
    return tuple(run_case(case) for case in discover_cases(root))


def result_to_dict(result: BenchmarkResult) -> dict[str, Any]:
    """Return a JSON-compatible representation with deterministic key values."""
    diagnostics = result.diagnostics
    external = result.external_scores
    return {
        "case": result.name,
        "pramana": {"before": result.pramana_before, "after": result.pramana_after},
        "score_path": list(result.score_path),
        "word_counts": {
            "source": diagnostics.source_word_count,
            "delivered": diagnostics.delivered_word_count,
            "delta": diagnostics.word_delta,
        },
        "relevant_terms_per_100_words": {
            "before": diagnostics.relevant_terms_per_100_words_before,
            "after": diagnostics.relevant_terms_per_100_words_after,
        },
        "proposals": [
            {
                "id": item.id,
                "operation": item.operation,
                "target": item.target,
                "status": item.status.value,
                "gate_code": item.gate_code.value if item.gate_code is not None else None,
                "score_delta": item.score_delta,
            }
            for item in diagnostics.proposals
        ],
        "counts": {
            "by_operation": dict(diagnostics.accepted_by_operation),
            "by_status": dict(diagnostics.proposals_by_status),
            "rejections_by_gate": dict(diagnostics.rejections_by_gate),
        },
        "sha256": {"source_projection": result.source_sha256, "delivered": result.delivered_sha256},
        "external_scores": (
            {
                "provider": external.provider,
                "base": external.base,
                "ats_ninja": external.ats_ninja,
                "manual": external.manual,
                "manual_gap_closure": external.manual_gap_closure,
            }
            if external is not None
            else None
        ),
    }


def format_report(results: tuple[BenchmarkResult, ...]) -> str:
    """Format a stable, human-readable report with all proposal records."""
    lines: list[str] = []
    for result in results:
        data = result_to_dict(result)
        lines.extend(
            (
                f"CASE {result.name}",
                f"  PRAMANA: {result.pramana_before:.2f} -> {result.pramana_after:.2f}",
                f"  score_path: {list(result.score_path)}",
                "  words: "
                f"{data['word_counts']['source']} -> {data['word_counts']['delivered']} "
                f"(delta {data['word_counts']['delta']:+d})",
                "  relevant_terms_per_100_words: "
                f"{data['relevant_terms_per_100_words']['before']:.3f} -> "
                f"{data['relevant_terms_per_100_words']['after']:.3f}",
                f"  sha256 source_projection: {result.source_sha256}",
                f"  sha256 delivered: {result.delivered_sha256}",
                f"  counts by operation: {json.dumps(data['counts']['by_operation'], sort_keys=True)}",
                f"  counts by status: {json.dumps(data['counts']['by_status'], sort_keys=True)}",
                f"  rejections by gate: {json.dumps(data['counts']['rejections_by_gate'], sort_keys=True)}",
                "  proposals:",
            )
        )
        for proposal in data["proposals"]:
            lines.append(
                "    "
                f"{proposal['id']} | {proposal['operation']} | {proposal['target']} | "
                f"{proposal['status']} | {proposal['gate_code'] or '-'} | "
                f"{proposal['score_delta'] if proposal['score_delta'] is not None else '-'}"
            )
        if result.external_scores is not None:
            external = result.external_scores
            manual = "-" if external.manual is None else f"{external.manual:.2f}"
            closure = external.manual_gap_closure
            closure_text = "-" if closure is None else f"{closure:.3f}"
            lines.append(
                "  external "
                f"{external.provider}: base={external.base:.2f}, ats_ninja={external.ats_ninja:.2f}, "
                f"manual={manual}, manual_gap_closure={closure_text}"
            )
    return "\n".join(lines)


def json_report(results: tuple[BenchmarkResult, ...]) -> str:
    """Return stable machine-readable benchmark output."""
    return json.dumps([result_to_dict(result) for result in results], indent=2, sort_keys=True) + "\n"


__all__ = [
    "BenchmarkCase",
    "BenchmarkResult",
    "ExternalScores",
    "discover_cases",
    "fixture_root",
    "format_report",
    "json_report",
    "load_external_scores",
    "run_all",
    "run_case",
]
