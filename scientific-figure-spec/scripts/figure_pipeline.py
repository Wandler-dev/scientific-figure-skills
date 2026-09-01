#!/usr/bin/env python3
"""Single-process structured-diagram execution pipeline for the unified CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diagram_plan import create_render_plan_file
from figure_coverage import coverage_is_complete
from figure_inspect import inspect_figure
from figure_runtime import preflight


class FigurePipelineError(RuntimeError):
    """Raised when a pipeline cannot start or an internal invariant fails."""


@dataclass
class PipelineResult:
    success: bool
    work_dir: Path
    preflight: dict[str, Any]
    backend: str = "drawio"
    plan_path: Path | None = None
    source_path: Path | None = None
    manifest_path: Path | None = None
    qa_path: Path | None = None
    export_status: str | None = None
    qa_outcome: str | None = None
    coverage_status: str | None = None
    coverage_issues: list[dict[str, str]] | None = None

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
            "coverage_issues": self.coverage_issues or [],
        }


def _coverage_issues(plan: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for section, code in (
        ("must_show", "scientific.coverage.must_show_unmapped"),
        ("relationships", "scientific.coverage.relationship_unmapped"),
    ):
        for item in plan["spec_coverage"][section]:
            if item["status"] == "UNRESOLVED":
                result.append(
                    {
                        "code": code,
                        "source_ref": item["source_ref"],
                        "message": item.get("reason", "Unresolved FigureSpec content."),
                    }
                )
    return result


def run_figure_pipeline(
    *,
    figure_spec_path: Path,
    work_dir: Path,
    backend: str,
    drawio_command: str | None = None,
    svg_renderer_command: str | None = None,
    formats: list[str] | None = None,
    strict_spec: bool = True,
    strict_lint: bool = True,
    overwrite: bool = False,
    timeout_seconds: int = 60,
) -> PipelineResult:
    if backend not in {"drawio", "svg"}:
        raise FigurePipelineError(f"Unsupported structured-diagram backend: {backend}")
    figure_spec_path = figure_spec_path.expanduser().resolve()
    work_dir = work_dir.expanduser().resolve()
    readiness = preflight(
        backend=backend,
        operation="render",
        drawio_command=drawio_command,
        svg_renderer_command=svg_renderer_command,
    )
    if not readiness["ready"]:
        return PipelineResult(
            success=False,
            backend=backend,
            work_dir=work_dir,
            preflight=readiness,
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    stem = figure_spec_path.stem
    plan_path = work_dir / f"{stem}.render-plan.json"
    manifest_path = work_dir / f"{stem}.manifest.json"
    qa_path = work_dir / f"{stem}.qa.json"
    artifact_dir = work_dir / "artifacts"

    plan = create_render_plan_file(
        figure_spec_path,
        plan_path,
        backend=backend,
        strict=strict_spec,
        overwrite=overwrite,
    )
    source_path = work_dir / plan["outputs"]["source"]
    if not coverage_is_complete(plan):
        return PipelineResult(
            success=False,
            backend=backend,
            work_dir=work_dir,
            preflight=readiness,
            plan_path=plan_path,
            coverage_status="BLOCKED",
            coverage_issues=_coverage_issues(plan),
        )

    if backend == "drawio":
        from drawio_backend import write_drawio_source
        from drawio_export import export_drawio
        from drawio_lint import lint_drawio, lint_passed

        write_drawio_source(plan, source_path, overwrite=overwrite)
        lint_report = lint_drawio(source_path)
        if not lint_passed(lint_report, strict=strict_lint):
            raise FigurePipelineError(
                "Authored Draw.io source failed its own lint invariant; export was not invoked."
            )
        export_result = export_drawio(
            plan_path=plan_path,
            source_path=source_path,
            output_dir=artifact_dir,
            formats=formats,
            drawio_command=drawio_command,
            manifest_path=manifest_path,
            overwrite=overwrite,
            strict_lint=strict_lint,
            timeout_seconds=timeout_seconds,
        )
    else:
        from svg_backend import write_svg_source
        from svg_export import export_svg
        from svg_lint import lint_passed, lint_svg

        write_svg_source(plan, source_path, overwrite=overwrite)
        lint_report = lint_svg(source_path, plan=plan)
        if not lint_passed(lint_report, strict=strict_lint):
            raise FigurePipelineError(
                "Authored native SVG source failed its own lint invariant; export was not invoked."
            )
        export_result = export_svg(
            plan_path=plan_path,
            source_path=source_path,
            output_dir=artifact_dir,
            formats=formats,
            renderer_command=svg_renderer_command,
            manifest_path=manifest_path,
            overwrite=overwrite,
            strict_lint=strict_lint,
            timeout_seconds=timeout_seconds,
        )

    inspection_result = inspect_figure(
        plan_path=plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        qa_path=qa_path,
        overwrite=overwrite,
    )
    success = export_result.success and inspection_result.passed
    return PipelineResult(
        success=success,
        backend=backend,
        work_dir=work_dir,
        preflight=readiness,
        plan_path=plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        qa_path=qa_path,
        export_status=export_result.manifest["status"],
        qa_outcome=inspection_result.report["outcome"],
        coverage_status=plan["spec_coverage"]["status"],
    )


def run_drawio_pipeline(
    *,
    figure_spec_path: Path,
    work_dir: Path,
    backend: str,
    drawio_command: str | None,
    formats: list[str] | None = None,
    strict_spec: bool = True,
    strict_lint: bool = True,
    overwrite: bool = False,
    timeout_seconds: int = 60,
) -> PipelineResult:
    """Compatibility wrapper for the v1.1 Draw.io pipeline entry point."""

    return run_figure_pipeline(
        figure_spec_path=figure_spec_path,
        work_dir=work_dir,
        backend=backend,
        drawio_command=drawio_command,
        formats=formats,
        strict_spec=strict_spec,
        strict_lint=strict_lint,
        overwrite=overwrite,
        timeout_seconds=timeout_seconds,
    )


def format_pipeline_result(result: PipelineResult) -> str:
    backend_label = "Draw.io" if result.backend == "drawio" else "Native SVG"
    if not result.preflight.get("ready"):
        lines = [f"[BLOCKED] {backend_label} pipeline preflight"]
        for issue in result.preflight.get("issues", []):
            lines.append(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
        return "\n".join(lines)
    if result.coverage_status == "BLOCKED":
        lines = ["[BLOCKED] FigureSpec coverage gate", f"RenderPlan: {result.plan_path}"]
        for issue in result.coverage_issues or []:
            lines.append(
                f"[BLOCKING] {issue['code']} ({issue['source_ref']}): {issue['message']}"
            )
        return "\n".join(lines)
    lines = [
        f"[{'AUTOMATED CHECKS PASSED' if result.success else 'FAIL'}] {backend_label} execution pipeline",
        f"Work directory: {result.work_dir}",
        f"RenderPlan: {result.plan_path}",
        f"Editable source: {result.source_path}",
        f"Manifest: {result.manifest_path}",
        f"QA report: {result.qa_path}",
        f"Export status: {result.export_status}",
        f"QA outcome: {result.qa_outcome}",
    ]
    return "\n".join(lines)
