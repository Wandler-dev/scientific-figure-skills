#!/usr/bin/env python3
"""Create a conservative PlotPlan 1.0 scaffold from FigureSpec 1.0.

The planner records authoritative inputs and every FigureSpec requirement, but
does not guess column semantics. An agent or researcher completes panel and
binding decisions before the Data Binding Gate permits rendering.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import validate_figure_spec as figure_spec_validator
from figure_runtime import (
    sha256_file,
    validate_plot_plan_contract,
    write_json_atomic,
)


class PlotPlanError(RuntimeError):
    """Raised when a safe PlotPlan scaffold cannot be created."""


SECTION_REQUIREMENTS = {
    "must_show": "3.1 Must Show",
    "relationships": "4.1 Relationships",
    "required_labels": "6.2 Required Figure Labels",
    "must_not_imply": "6.3 Must Not Imply / Avoid",
}


def _bullet_items(body: str | None) -> list[str]:
    if body is None:
        return []
    cleaned = figure_spec_validator.HTML_COMMENT_RE.sub("", body)
    result: list[str] = []
    for line in cleaned.splitlines():
        match = re.match(r"^\s*[-*+]\s+(?P<item>.+?)\s*$", line)
        if match is None:
            continue
        item = match.group("item").strip()
        if item.casefold() not in figure_spec_validator.PLACEHOLDER_VALUES:
            result.append(item)
    return result


def extract_plot_requirements(spec_path: Path) -> dict[str, list[str]]:
    text = spec_path.read_text(encoding="utf-8")
    headings = figure_spec_validator.collect_headings(text)
    return {
        key: _bullet_items(figure_spec_validator.section_body(text, headings, title))
        for key, title in SECTION_REQUIREMENTS.items()
    }


def _unresolved_coverage(requirements: dict[str, list[str]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for section, values in requirements.items():
        title = SECTION_REQUIREMENTS[section]
        coverage[section] = [
            {
                "id": f"{section.replace('_', '-')}-{index:03d}",
                "source_ref": f"{title}[{index}]",
                "source_text": value,
                "status": "UNRESOLVED",
                "representations": [],
                "reason": "Column, panel, and visual encoding must be explicitly bound.",
            }
            for index, value in enumerate(values, start=1)
        ]
    summary: dict[str, int] = {}
    for section in SECTION_REQUIREMENTS:
        summary[f"{section}_total"] = len(coverage[section])
        summary[f"{section}_mapped"] = 0
    summary["unresolved_total"] = sum(summary[f"{key}_total"] for key in SECTION_REQUIREMENTS)
    coverage["summary"] = summary
    coverage["status"] = "BLOCKED" if summary["unresolved_total"] else "COMPLETE"
    return coverage


def _parse_formats(value: str | None) -> list[str]:
    lowered = (value or "").casefold()
    formats = [item for item in ("svg", "pdf", "png") if item in lowered]
    return formats or ["svg", "pdf", "png"]


def _parse_target_size(value: str | None) -> tuple[float, float, str]:
    if value:
        physical = re.search(
            r"(?P<width>\d+(?:\.\d+)?)\s*(?P<unit>mm|in|inch(?:es)?)\s*[x×]\s*"
            r"(?P<height>\d+(?:\.\d+)?)\s*(?P=unit)?",
            value,
            flags=re.I,
        )
        if physical:
            unit = physical.group("unit").casefold()
            return (
                float(physical.group("width")),
                float(physical.group("height")),
                "in" if unit.startswith("in") else "mm",
            )
        ratio = re.search(r"(?P<ratio>\d+(?:\.\d+)?)\s*:\s*1", value)
        if ratio:
            width = 180.0
            return width, round(width / float(ratio.group("ratio")), 3), "mm"
    return 180.0, 100.0, "mm"


def _data_format(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    if suffix == ".json":
        return "json-records"
    raise PlotPlanError(
        f"Unsupported authoritative plotting data extension {path.suffix!r}; use CSV, TSV, or JSON records."
    )


def build_plot_plan_scaffold(
    spec_path: Path,
    plan_path: Path,
    *,
    data_paths: list[Path] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    spec_path = spec_path.expanduser().resolve()
    plan_path = plan_path.expanduser().resolve()
    if not spec_path.is_file():
        raise PlotPlanError(f"FigureSpec does not exist: {spec_path}")
    report = figure_spec_validator.validate_file(spec_path, project_root=None)
    blocking = list(report.errors) + (list(report.warnings) if strict else [])
    if blocking:
        details = "; ".join(f"{item.code}: {item.message}" for item in blocking)
        raise PlotPlanError(f"FigureSpec validation failed: {details}")

    text = spec_path.read_text(encoding="utf-8")
    metadata, error = figure_spec_validator.extract_frontmatter(text)
    if error or not isinstance(metadata, dict):
        raise PlotPlanError(error or "FigureSpec frontmatter is invalid.")
    headings = figure_spec_validator.collect_headings(text)
    render_body = figure_spec_validator.section_body(
        text, headings, "7.3 Rendering Requirements"
    )
    target_field = figure_spec_validator.extract_bold_field(
        render_body, "Target Size / Aspect Ratio"
    )
    required_outputs = figure_spec_validator.extract_bold_field(
        render_body, "Required Outputs"
    )
    width, height, unit = _parse_target_size(target_field)

    declarations: list[dict[str, Any]] = []
    for index, raw_path in enumerate(data_paths or [], start=1):
        path = raw_path.expanduser().resolve()
        if not path.is_file():
            raise PlotPlanError(f"Authoritative plotting data is not a regular file: {path}")
        try:
            relative = os.path.relpath(path, plan_path.parent)
        except ValueError:
            relative = str(path)
        declarations.append(
            {
                "id": f"data-{index:03d}",
                "path": relative,
                "format": _data_format(path),
                "sha256": sha256_file(path),
                "role": "authoritative_plot_data",
            }
        )

    try:
        relative_spec = os.path.relpath(spec_path, plan_path.parent)
    except ValueError:
        relative_spec = str(spec_path)
    figure_id = metadata.get("figure_id")
    stem = spec_path.stem
    coverage = _unresolved_coverage(extract_plot_requirements(spec_path))
    plan = {
        "schema_version": "1.0",
        "plan_id": f"{figure_id}-matplotlib-v1",
        "figure_id": figure_id,
        "backend": "matplotlib",
        "figure_spec": {
            "path": relative_spec,
            "sha256": sha256_file(spec_path),
            "spec_version": metadata.get("spec_version"),
            "figure_id": figure_id,
        },
        "target": {
            "width": width,
            "height": height,
            "unit": unit,
            "dpi": 300,
            "minimum_text_size_pt": 6.5,
        },
        "data_sources": declarations,
        "spec_coverage": coverage,
        "layout": {"rows": 1, "columns": 1, "shared_legend": False},
        "panels": [],
        "style_profile": "publication-default",
        "outputs": {
            "source": f"{stem}.plot.py",
            "formats": _parse_formats(required_outputs),
            "manifest": f"{stem}.manifest.json",
            "qa_report": f"{stem}.qa.json",
            "trace": f"{stem}.plot-trace.json",
        },
        "checks": {
            "grayscale_distinguishability": True,
            "vector_text": True,
            "data_binding": True,
        },
        "metadata": {
            "generated_by": "scientific-figure-skills",
            "source_status": metadata.get("status"),
            "working_title": metadata.get("working_title"),
            "planning_mode": "conservative_scaffold",
            "requires_explicit_panel_and_column_binding": True,
        },
    }
    issues = validate_plot_plan_contract(plan)
    if any(item.severity == "ERROR" for item in issues):
        details = "; ".join(f"{item.code}: {item.message}" for item in issues)
        raise PlotPlanError(f"Generated PlotPlan scaffold is invalid: {details}")
    return plan


def create_plot_plan_file(
    spec_path: Path,
    plan_path: Path,
    *,
    data_paths: list[Path] | None = None,
    strict: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    plan = build_plot_plan_scaffold(
        spec_path,
        plan_path,
        data_paths=data_paths,
        strict=strict,
    )
    write_json_atomic(plan_path, plan, overwrite=overwrite)
    return plan
