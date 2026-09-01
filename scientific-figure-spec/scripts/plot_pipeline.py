#!/usr/bin/env python3
"""Controlled PlotPlan → Matplotlib → artifact QA pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from figure_runtime import preflight, read_json
from matplotlib_backend import (
    author_plot_source,
    export_matplotlib,
    lint_plot_source,
    plot_source_lint_passed,
)
from plot_binding import validate_data_binding
from plot_inspect import inspect_plot


class PlotPipelineError(RuntimeError):
    """Raised when the quantitative plot pipeline cannot proceed safely."""


@dataclass
class PlotPipelineResult:
    success: bool
    work_dir: Path
    preflight: dict[str, Any]
    backend: str = "matplotlib"
    plan_path: Path | None = None
    source_path: Path | None = None
    manifest_path: Path | None = None
    qa_path: Path | None = None
    export_status: str | None = None
    qa_outcome: str | None = None
    coverage_status: str | None = None
    binding_status: str | None = None
    binding_issues: list[dict[str, str]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "backend": self.backend,
            "work_dir": str(self.work_dir),
            "preflight": self.preflight,
            "plan_path": str(self.plan_path) if self.plan_path else None,
            "source_path": str(self.source_path) if self.source_path else None,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "qa_path": str(self.qa_path) if self.qa_path else None,
            "export_status": self.export_status,
            "qa_outcome": self.qa_outcome,
            "coverage_status": self.coverage_status,
            "binding_status": self.binding_status,
            "binding_issues": self.binding_issues or [],
        }


def run_plot_pipeline(
    *,
    plot_plan_path: Path,
    work_dir: Path,
    formats: list[str] | None = None,
    strict_lint: bool = True,
    overwrite: bool = False,
    timeout_seconds: int = 60,
) -> PlotPipelineResult:
    plot_plan_path = plot_plan_path.expanduser().resolve()
    work_dir = work_dir.expanduser().resolve()
    readiness = preflight(backend="matplotlib", operation="render")
    if not readiness["ready"]:
        return PlotPipelineResult(False, work_dir, readiness, plan_path=plot_plan_path)
    plan = read_json(plot_plan_path)
    if not isinstance(plan, dict) or plan.get("backend") != "matplotlib":
        raise PlotPipelineError("Matplotlib render requires a PlotPlan 1.0 JSON file.")
    binding = validate_data_binding(plot_plan_path, plan=plan)
    coverage_status = plan.get("spec_coverage", {}).get("status")
    if not binding.passed:
        return PlotPipelineResult(
            False,
            work_dir,
            readiness,
            plan_path=plot_plan_path,
            coverage_status=coverage_status,
            binding_status="BLOCKED",
            binding_issues=[item.as_dict() for item in binding.issues],
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    source_path = work_dir / plan["outputs"]["source"]
    manifest_path = work_dir / plan["outputs"]["manifest"]
    qa_path = work_dir / plan["outputs"]["qa_report"]
    artifact_dir = work_dir / "artifacts"
    author_plot_source(plot_plan_path, source_path, overwrite=overwrite)
    lint = lint_plot_source(source_path, plan_path=plot_plan_path)
    if not plot_source_lint_passed(lint, strict=strict_lint):
        raise PlotPipelineError("Authored plot source failed its own lint invariant.")
    exported = export_matplotlib(
        plan_path=plot_plan_path,
        source_path=source_path,
        output_dir=artifact_dir,
        formats=formats,
        manifest_path=manifest_path,
        overwrite=overwrite,
        strict_lint=strict_lint,
        timeout_seconds=timeout_seconds,
    )
    if not exported.success:
        return PlotPipelineResult(
            False,
            work_dir,
            readiness,
            plan_path=plot_plan_path,
            source_path=source_path,
            manifest_path=manifest_path,
            export_status=exported.manifest["status"],
            coverage_status=coverage_status,
            binding_status="COMPLETE",
        )
    inspection = inspect_plot(
        plan_path=plot_plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        qa_path=qa_path,
        overwrite=overwrite,
    )
    return PlotPipelineResult(
        inspection.passed,
        work_dir,
        readiness,
        plan_path=plot_plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        qa_path=qa_path,
        export_status=exported.manifest["status"],
        qa_outcome=inspection.report["outcome"],
        coverage_status=coverage_status,
        binding_status="COMPLETE",
    )


def format_pipeline_result(result: PlotPipelineResult) -> str:
    if not result.preflight.get("ready"):
        lines = ["[BLOCKED] Matplotlib pipeline preflight"]
        lines.extend(
            f"[{item['severity']}] {item['code']}: {item['message']}"
            for item in result.preflight.get("issues", [])
        )
        return "\n".join(lines)
    if result.binding_status == "BLOCKED":
        lines = ["[BLOCKED] PlotPlan data binding"]
        lines.extend(
            f"[{item['severity']}] {item['code']}: {item['message']}"
            for item in result.binding_issues or []
        )
        return "\n".join(lines)
    return "\n".join(
        [
            f"[{'AUTOMATED CHECKS PASSED' if result.success else 'FAIL'}] Matplotlib execution pipeline",
            f"PlotPlan: {result.plan_path}",
            f"Source: {result.source_path}",
            f"Manifest: {result.manifest_path}",
            f"QA: {result.qa_path}",
            f"Export: {result.export_status}",
            f"QA outcome: {result.qa_outcome}",
        ]
    )
