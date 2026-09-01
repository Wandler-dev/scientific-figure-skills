#!/usr/bin/env python3
"""Inspect data-bound Matplotlib artifacts without OCR or statistical inference."""

from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_utils import inspect_artifact_dimensions
from figure_runtime import (
    RuntimeContractError,
    RuntimeIssue,
    read_json,
    sha256_file,
    utc_now,
    validate_manifest_contract,
    validate_plot_plan_contract,
    validate_qa_contract,
    write_json_atomic,
)
from matplotlib_backend import (
    DEFAULT_COLORS,
    DEFAULT_HATCHES,
    DEFAULT_LINE_STYLES,
    DEFAULT_MARKERS,
    lint_plot_source,
    plot_source_lint_passed,
)
from plot_binding import validate_data_binding


SVG_NS = "http://www.w3.org/2000/svg"


class PlotInspectionError(RuntimeError):
    """Raised when plot inspection inputs cannot be read safely."""


@dataclass
class PlotInspectionResult:
    qa_path: Path
    report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.report.get("outcome") == "AUTOMATED_CHECKS_PASSED"


def _portable_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), base.resolve())
    except ValueError:
        return str(path.resolve())


def _qa_ref(path: Path, base: Path) -> dict[str, str]:
    return {"path": _portable_path(path, base), "sha256": sha256_file(path)}


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _qa_issue(
    severity: str,
    category: str,
    code: str,
    issue: str,
    why: str,
    fix: str,
    repairability: str,
    *,
    artifact: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "code": code,
        "issue": issue,
        "why_it_matters": why,
        "recommended_fix": fix,
        "repairability": repairability,
    }
    if artifact is not None:
        result["location"] = {"artifact": artifact}
    if evidence:
        result["evidence"] = evidence
    return result


def _runtime_to_qa(issue: RuntimeIssue | dict[str, Any]) -> dict[str, Any]:
    severity_value = issue.severity if isinstance(issue, RuntimeIssue) else str(issue.get("severity", "ERROR"))
    code = issue.code if isinstance(issue, RuntimeIssue) else str(issue.get("code", "plot.inspection.failed"))
    message = issue.message if isinstance(issue, RuntimeIssue) else str(issue.get("message", "Plot inspection failed."))
    severity = "BLOCKING" if severity_value == "ERROR" else "MINOR"
    if code.startswith(("plot.axis", "scientific.")):
        category = "Scientific"
    elif code.startswith(("plot.style", "plot.text")):
        category = "Visual"
    elif code.startswith("plot.series"):
        category = "Communication"
    else:
        category = "Technical"
    return _qa_issue(
        severity,
        category,
        code,
        message,
        "The delivered plot must remain bound to its declared scientific and data contract.",
        "Correct the PlotPlan, authoritative input, or generated artifact and rerun the pipeline.",
        "NEEDS_SCIENTIFIC_INPUT" if category == "Scientific" else "SAFE_LOCAL",
    )


def _target_inches(target: dict[str, Any]) -> tuple[float, float]:
    if target["unit"] == "mm":
        return float(target["width"]) / 25.4, float(target["height"]) / 25.4
    return float(target["width"]), float(target["height"])


def _number_with_unit(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)", value)
    if not match:
        return None, None
    return float(match.group(1)), match.group(2).casefold() or None


def _inspect_svg(
    path: Path,
    target: dict[str, Any],
    *,
    require_text: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return [
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.svg_invalid",
                f"SVG is not parseable: {exc}",
                "A broken vector artifact cannot be published or inspected.",
                "Regenerate the SVG from the bound PlotPlan.",
                "SAFE_LOCAL",
                artifact=str(path),
            )
        ]
    if root.tag.rsplit("}", 1)[-1] != "svg":
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.svg_root_invalid",
                "Vector output root is not <svg>.",
                "The declared SVG artifact must be a real SVG document.",
                "Regenerate the SVG output.",
                "SAFE_LOCAL",
                artifact=str(path),
            )
        )
    text_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"text", "tspan"} and "".join(node.itertext()).strip()]
    if require_text and not text_nodes:
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.live_text_missing",
                "Matplotlib SVG contains no meaningful live text nodes.",
                "Publication labels must remain searchable and editable.",
                "Use svg.fonttype='none' and regenerate.",
                "SAFE_LOCAL",
                artifact=str(path),
            )
        )
    images = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "image"]
    if images:
        issues.append(
            _qa_issue(
                "MAJOR",
                "Technical",
                "plot.output.svg_raster_embedded",
                f"SVG contains {len(images)} embedded raster image element(s).",
                "A requested vector plot should preserve vector marks where the backend supports them.",
                "Use vector-native plot marks and regenerate.",
                "NEEDS_DESIGN",
                artifact=str(path),
            )
        )
    expected_width_in, expected_height_in = _target_inches(target)
    width, width_unit = _number_with_unit(root.get("width"))
    height, height_unit = _number_with_unit(root.get("height"))
    if width is not None and height is not None:
        if width_unit == "pt":
            actual = (width / 72.0, height / 72.0)
        elif width_unit == "in":
            actual = (width, height)
        elif width_unit == "mm":
            actual = (width / 25.4, height / 25.4)
        else:
            actual = None
        if actual and (
            abs(actual[0] - expected_width_in) > 0.03
            or abs(actual[1] - expected_height_in) > 0.03
        ):
            issues.append(
                _qa_issue(
                    "MAJOR",
                    "Visual",
                    "plot.output.final_size_mismatch",
                    "SVG physical dimensions do not match PlotPlan target size.",
                    "Final-size typography and visual density depend on physical dimensions.",
                    "Export without tight bounding-box resizing and preserve the target canvas.",
                    "SAFE_LOCAL",
                    artifact=str(path),
                )
            )
    return issues


def _inspect_dimensions(
    path: Path,
    format_name: str,
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    dimensions = inspect_artifact_dimensions(path, format_name)
    if dimensions is None:
        return [
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.dimension_invalid",
                f"Could not verify {format_name.upper()} dimensions/header.",
                "Artifact format and page/canvas dimensions must be genuine.",
                "Regenerate the requested output.",
                "SAFE_LOCAL",
                artifact=str(path),
            )
        ]
    expected_width_in, expected_height_in = _target_inches(target)
    if format_name == "png":
        expected_width = round(expected_width_in * target["dpi"])
        expected_height = round(expected_height_in * target["dpi"])
        tolerance = 3
        actual_width = dimensions["width"]
        actual_height = dimensions["height"]
    elif format_name == "pdf":
        expected_width = expected_width_in * 72
        expected_height = expected_height_in * 72
        tolerance = 2
        actual_width = dimensions["width"]
        actual_height = dimensions["height"]
    else:
        return []
    if abs(actual_width - expected_width) > tolerance or abs(actual_height - expected_height) > tolerance:
        return [
            _qa_issue(
                "MAJOR",
                "Visual",
                "plot.output.final_size_mismatch",
                f"{format_name.upper()} dimensions do not match the PlotPlan target size.",
                "Final-size readability cannot be assessed against a resized canvas.",
                "Preserve the declared target dimensions during export.",
                "SAFE_LOCAL",
                artifact=str(path),
                evidence=[f"expected={expected_width}x{expected_height}", f"actual={actual_width}x{actual_height}"],
            )
        ]
    return []


def _inspect_pdf_vector(path: Path) -> list[dict[str, Any]]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        return [
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.pdf_read_failed",
                f"Could not read PDF for vector inspection: {exc}",
                "A publication vector artifact must be inspectable.",
                "Regenerate the PDF output.",
                "SAFE_LOCAL",
                artifact=str(path),
            )
        ]
    image_objects = payload.count(b"/Subtype /Image") + payload.count(b"/Subtype/Image")
    if image_objects:
        return [
            _qa_issue(
                "MAJOR",
                "Technical",
                "plot.output.pdf_raster_embedded",
                f"PDF contains {image_objects} embedded raster image object(s).",
                "The supported PlotPlan 1.0 marks should remain vector in publication PDF output.",
                "Use vector-native plot marks and regenerate.",
                "NEEDS_DESIGN",
                artifact=str(path),
            )
        ]
    return []


def _normalized_label(value: Any) -> str:
    return " ".join(str(value).split())


def _required_label_text(value: Any) -> str:
    label = _normalized_label(value)
    # FigureSpec bullet prose commonly ends each label with sentence punctuation;
    # the rendered label itself does not need that terminal full stop.
    return label[:-1] if label.endswith(".") else label


def _svg_live_labels(path: Path) -> set[str]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return set()
    return {
        _normalized_label("".join(node.itertext()))
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "text"
        and _normalized_label("".join(node.itertext()))
    }


def _expected_svg_labels(plan: dict[str, Any], binding: Any) -> set[str]:
    labels: set[str] = set()
    for item in plan.get("spec_coverage", {}).get("required_labels", []):
        if isinstance(item, dict) and item.get("status") == "MAPPED":
            labels.add(_required_label_text(item.get("source_text", "")))
    resolved_by_id = {
        item.get("panel_id"): item
        for item in binding.resolved_panels
        if isinstance(item, dict)
    }
    for panel in plan.get("panels", []):
        if not isinstance(panel, dict):
            continue
        if panel.get("title"):
            labels.add(_normalized_label(panel["title"]))
        axes = panel.get("axes", {})
        for axis_name in ("x", "y"):
            axis = axes.get(axis_name) if isinstance(axes, dict) else None
            if isinstance(axis, dict) and axis.get("label"):
                label = str(axis["label"])
                if axis.get("unit"):
                    label = f"{label} ({axis['unit']})"
                labels.add(_normalized_label(label))
        legend_mode = panel.get("legend", {}).get("mode")
        if legend_mode in {"panel", "figure"}:
            labels.update(
                _normalized_label(series["label"])
                for series in panel.get("series", [])
                if isinstance(series, dict) and series.get("label")
            )
        labels.update(
            _normalized_label(annotation["text"])
            for annotation in panel.get("annotations", [])
            if isinstance(annotation, dict) and annotation.get("text")
        )
        labels.update(
            _normalized_label(reference["label"])
            for reference in panel.get("reference_lines", [])
            if isinstance(reference, dict) and reference.get("label")
        )
        resolved = resolved_by_id.get(panel.get("id"), {})
        if panel.get("plot_type") == "bar":
            categories = list(panel.get("category_order") or [])
            if not categories:
                for series in resolved.get("series", []):
                    for category in series.get("category", []):
                        if category not in categories:
                            categories.append(category)
            labels.update(_normalized_label(item) for item in categories)
        if panel.get("plot_type") == "heatmap":
            for cell in resolved.get("cells", []):
                labels.add(_normalized_label(cell.get("x", "")))
                labels.add(_normalized_label(cell.get("y", "")))
            color_scale = panel.get("color_scale", {})
            if isinstance(color_scale, dict) and color_scale.get("label"):
                label = str(color_scale["label"])
                if color_scale.get("unit"):
                    label = f"{label} ({color_scale['unit']})"
                labels.add(_normalized_label(label))
    labels.discard("")
    return labels


def _summary(issues: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "blocking": sum(item["severity"] == "BLOCKING" for item in issues),
        "major": sum(item["severity"] == "MAJOR" for item in issues),
        "minor": sum(item["severity"] == "MINOR" for item in issues),
    }


def _dedupe_runtime_issues(
    issues: list[RuntimeIssue | dict[str, Any]],
) -> list[RuntimeIssue | dict[str, Any]]:
    result: list[RuntimeIssue | dict[str, Any]] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    pathful_semantics = {
        (item.severity, item.code, item.message)
        for item in issues
        if isinstance(item, RuntimeIssue)
    }
    for item in issues:
        if isinstance(item, RuntimeIssue):
            key = (item.severity, item.code, item.message, item.path)
        else:
            key = (
                str(item.get("severity", "ERROR")),
                str(item.get("code", "plot.inspection.failed")),
                str(item.get("message", "Plot inspection failed.")),
                None,
            )
            # Manifest issue records cannot retain RuntimeIssue.path. Suppress
            # a pathless copy when plan validation, lint, or data binding has
            # already reported the same finding.
            if key[:3] in pathful_semantics:
                continue
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _luminance(color: str) -> float:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        return 0.5
    red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _grayscale_issues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if not plan.get("checks", {}).get("grayscale_distinguishability"):
        return []
    issues: list[dict[str, Any]] = []
    for panel in plan.get("panels", []):
        if not isinstance(panel, dict) or panel.get("plot_type") == "heatmap":
            continue
        signatures: list[tuple[str, float, str, str]] = []
        for index, series in enumerate(panel.get("series", [])):
            if not isinstance(series, dict):
                continue
            color = series.get("color", DEFAULT_COLORS[index % len(DEFAULT_COLORS)])
            marker = series.get("marker", DEFAULT_MARKERS[index % len(DEFAULT_MARKERS)])
            line_style = series.get(
                "line_style", DEFAULT_LINE_STYLES[index % len(DEFAULT_LINE_STYLES)]
            )
            hatch = series.get("hatch", DEFAULT_HATCHES[index % len(DEFAULT_HATCHES)])
            signatures.append((str(series.get("id")), _luminance(str(color)), str(marker), str(line_style if panel["plot_type"] != "bar" else hatch)))
        for left_index, left in enumerate(signatures):
            for right in signatures[left_index + 1 :]:
                if left[2:] == right[2:] and abs(left[1] - right[1]) < 0.12:
                    issues.append(
                        _qa_issue(
                            "MINOR",
                            "Visual",
                            "plot.style.grayscale_indistinguishable",
                            f"Series {left[0]!r} and {right[0]!r} may be difficult to distinguish in grayscale.",
                            "Critical series should not rely on nearly identical luminance alone.",
                            "Use a distinct marker, line style, or hatch for one series.",
                            "NEEDS_DESIGN",
                        )
                    )
    return issues


def inspect_plot(
    *,
    plan_path: Path,
    source_path: Path,
    manifest_path: Path,
    qa_path: Path | None = None,
    overwrite: bool = False,
) -> PlotInspectionResult:
    plan_path = plan_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
        manifest = read_json(manifest_path)
    except RuntimeContractError as exc:
        raise PlotInspectionError(str(exc)) from exc
    if not isinstance(plan, dict) or not isinstance(manifest, dict):
        raise PlotInspectionError("PlotPlan and artifact manifest must be JSON objects.")
    if qa_path is None:
        qa_path = plan_path.parent / plan["outputs"]["qa_report"]
    qa_path = qa_path.expanduser()
    if not qa_path.is_absolute():
        qa_path = plan_path.parent / qa_path
    qa_path = qa_path.resolve()

    runtime_issues: list[RuntimeIssue | dict[str, Any]] = [
        *validate_plot_plan_contract(plan),
        *validate_manifest_contract(manifest),
    ]
    lint = lint_plot_source(source_path, plan_path=plan_path)
    runtime_issues.extend(lint.issues)
    binding = validate_data_binding(plan_path, plan=plan)
    runtime_issues.extend(binding.issues)
    runtime_issues.extend(
        item for item in manifest.get("issues", []) if isinstance(item, dict)
    )
    issues = [_runtime_to_qa(item) for item in _dedupe_runtime_issues(runtime_issues)]
    issues.extend(_grayscale_issues(plan))
    checks: list[dict[str, Any]] = []

    if manifest.get("status") != "COMPLETED":
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.manifest_incomplete",
                f"Artifact manifest status is {manifest.get('status')!r}, not 'COMPLETED'.",
                "Only a completed export can satisfy reproducibility checks.",
                "Resolve export issues and rerun.",
                "SAFE_LOCAL",
            )
        )
    for key, expected_path in (("plan", plan_path), ("source", source_path)):
        reference = manifest.get(key)
        if isinstance(reference, dict):
            if reference.get("sha256") != sha256_file(expected_path):
                issues.append(
                    _qa_issue(
                        "BLOCKING",
                        "Technical",
                        f"plot.output.{key}_hash_mismatch",
                        f"Manifest {key} hash does not match the inspected file.",
                        "Execution provenance must identify the exact plan and source.",
                        "Regenerate artifacts and manifest together.",
                        "SAFE_LOCAL",
                    )
                )

    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    input_records = metadata.get("inputs") if isinstance(metadata, dict) else None
    records_by_id = {
        item.get("id"): item
        for item in input_records
        if isinstance(input_records, list) and isinstance(item, dict)
    } if isinstance(input_records, list) else {}
    for source_id, data in binding.datasets.items():
        record = records_by_id.get(source_id)
        if not isinstance(record, dict):
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Technical",
                    "plot.output.input_provenance_missing",
                    f"Manifest does not record authoritative data input {source_id!r}.",
                    "Reproducibility requires every plotted data source path and hash.",
                    "Regenerate the export manifest.",
                    "SAFE_LOCAL",
                )
            )
        elif record.get("sha256") != data.sha256:
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Scientific",
                    "plot.output.input_hash_mismatch",
                    f"Manifest hash for data input {source_id!r} differs from the authoritative file.",
                    "The delivered plot may not correspond to the declared data revision.",
                    "Regenerate from the current authoritative data.",
                    "NEEDS_SCIENTIFIC_INPUT",
                )
            )
    trace_ref = metadata.get("resolved_trace") if isinstance(metadata, dict) else None
    trace_path: Path | None = None
    actual_trace: dict[str, Any] | None = None
    trace_artifacts: dict[str, dict[str, Any]] = {}
    if not isinstance(trace_ref, dict) or not isinstance(trace_ref.get("path"), str):
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.source.trace_missing",
                "Artifact manifest does not record a resolved execution trace.",
                "The trace proves which columns and rows the renderer actually used.",
                "Rerun Matplotlib export with trace recording enabled.",
                "SAFE_LOCAL",
            )
        )
    else:
        trace_path = _resolve(trace_ref["path"], manifest_path.parent)
        if not trace_path.is_file() or trace_ref.get("sha256") != sha256_file(trace_path):
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Technical",
                    "plot.source.trace_hash_mismatch",
                    "Resolved execution trace is missing or changed.",
                    "Plot execution must remain auditable against its recorded binding.",
                    "Regenerate the plot and manifest.",
                    "SAFE_LOCAL",
                )
            )
        else:
            trace_value = read_json(trace_path)
            actual_trace = trace_value if isinstance(trace_value, dict) else None
            if actual_trace is None:
                issues.append(
                    _qa_issue(
                        "BLOCKING",
                        "Technical",
                        "plot.source.trace_invalid",
                        "Resolved execution trace is not a JSON object.",
                        "Execution provenance must use the expected structured trace.",
                        "Regenerate the plot and manifest.",
                        "SAFE_LOCAL",
                    )
                )
            else:
                artifact_outputs = actual_trace.get("artifact_outputs")
                if not isinstance(artifact_outputs, list):
                    issues.append(
                        _qa_issue(
                            "BLOCKING",
                            "Technical",
                            "plot.source.artifact_trace_missing",
                            "Resolved execution trace does not identify its rendered artifacts.",
                            "Artifact hashes must be pinned by the execution that produced them, not only by the manifest.",
                            "Regenerate the plot and manifest with artifact trace recording enabled.",
                            "SAFE_LOCAL",
                        )
                    )
                else:
                    for trace_record in artifact_outputs:
                        format_name = (
                            trace_record.get("format")
                            if isinstance(trace_record, dict)
                            else None
                        )
                        if not isinstance(format_name, str) or format_name in trace_artifacts:
                            issues.append(
                                _qa_issue(
                                    "BLOCKING",
                                    "Technical",
                                    "plot.source.artifact_trace_invalid",
                                    "Resolved execution trace contains an invalid or duplicate artifact format.",
                                    "Each requested artifact must have one unambiguous execution identity.",
                                    "Regenerate the plot and manifest.",
                                    "SAFE_LOCAL",
                                )
                            )
                            continue
                        trace_artifacts[format_name] = trace_record
            for key, expected in binding.trace.items():
                if actual_trace is not None and actual_trace.get(key) != expected:
                    issues.append(
                        _qa_issue(
                            "BLOCKING",
                            "Scientific",
                            "scientific.data.execution_trace_mismatch",
                            f"Resolved trace field {key!r} differs from current authoritative binding.",
                            "The renderer may have used different rows, columns, or data revision.",
                            "Regenerate from the current PlotPlan and authoritative data.",
                            "NEEDS_SCIENTIFIC_INPUT",
                        )
                    )
                    break

    artifact_paths: list[Path] = []
    recorded_formats: set[str] = set()
    svg_live_labels: set[str] = set()
    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        path = _resolve(record["path"], manifest_path.parent)
        format_name = record.get("format")
        if isinstance(format_name, str):
            recorded_formats.add(format_name)
        if not path.is_file():
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Technical",
                    "plot.output.artifact_missing",
                    f"Recorded artifact is not a regular file: {path}",
                    "Requested deliverables must exist as real files.",
                    "Regenerate the missing output.",
                    "SAFE_LOCAL",
                    artifact=str(path),
                )
            )
            continue
        artifact_paths.append(path)
        actual_hash = sha256_file(path)
        if record.get("sha256") != actual_hash:
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Technical",
                    "technical.artifact.hash_mismatch",
                    f"Artifact changed after export: {path.name}",
                    "A changed artifact is no longer covered by recorded provenance.",
                    "Regenerate the manifest or restore the recorded artifact.",
                    "SAFE_LOCAL",
                    artifact=str(path),
                )
            )
            continue
        trace_record = trace_artifacts.get(format_name) if isinstance(format_name, str) else None
        if not isinstance(trace_record, dict) or any(
            (
                trace_record.get("sha256") != actual_hash,
                trace_record.get("size_bytes") != path.stat().st_size,
                trace_record.get("dimensions") != record.get("dimensions"),
            )
        ):
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Scientific",
                    "scientific.data.artifact_trace_mismatch",
                    f"Artifact {path.name!r} does not match the output identity recorded by its execution trace.",
                    "A manifest-only update could otherwise conceal scientific marks added after the bound render.",
                    "Regenerate the source, trace, manifest, and artifacts together from the current PlotPlan.",
                    "NEEDS_SCIENTIFIC_INPUT",
                    artifact=str(path),
                )
            )
        if format_name == "svg":
            issues.extend(_inspect_svg(path, plan["target"], require_text=plan["checks"]["vector_text"]))
            svg_live_labels.update(_svg_live_labels(path))
        if format_name in {"pdf", "png"}:
            issues.extend(_inspect_dimensions(path, format_name, plan["target"]))
        if format_name == "pdf":
            issues.extend(_inspect_pdf_vector(path))

    if "svg" in recorded_formats and svg_live_labels:
        missing_labels = sorted(_expected_svg_labels(plan, binding) - svg_live_labels)
        if missing_labels:
            issues.append(
                _qa_issue(
                    "BLOCKING",
                    "Communication",
                    "plot.output.planned_label_missing",
                    f"SVG is missing planned live labels: {missing_labels}.",
                    "Required, categorical, series, and axis labels must survive actual rendering.",
                    "Correct the Matplotlib authoring adapter or PlotPlan and regenerate.",
                    "SAFE_LOCAL",
                    evidence=[f"missing={item}" for item in missing_labels],
                )
            )

    missing_formats = set(plan["outputs"]["formats"]) - recorded_formats
    if missing_formats:
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.output.required_format_missing",
                f"Required plot formats are absent: {sorted(missing_formats)}.",
                "The delivered artifacts do not satisfy the PlotPlan output contract.",
                "Export every requested format.",
                "SAFE_LOCAL",
            )
        )

    unexpected_trace_formats = set(trace_artifacts) - recorded_formats
    if unexpected_trace_formats:
        issues.append(
            _qa_issue(
                "BLOCKING",
                "Technical",
                "plot.source.artifact_trace_mismatch",
                f"Execution trace records artifacts absent from the manifest: {sorted(unexpected_trace_formats)}.",
                "The execution trace and manifest must describe the same output set.",
                "Regenerate the plot and manifest together.",
                "SAFE_LOCAL",
            )
        )

    configured_minimum = None
    if actual_trace is not None:
        configured_minimum = actual_trace.get("minimum_configured_text_size_pt")
    if isinstance(configured_minimum, (int, float)) and configured_minimum < plan["target"]["minimum_text_size_pt"]:
        issues.append(
            _qa_issue(
                "MAJOR",
                "Visual",
                "visual.text.too_small",
                "Configured plot text falls below the PlotPlan final-size threshold.",
                "Labels may be unreadable at the intended physical size.",
                "Increase the scoped style font sizes or revise the layout.",
                "NEEDS_DESIGN",
                evidence=[f"configured={configured_minimum}pt", f"minimum={plan['target']['minimum_text_size_pt']}pt"],
            )
        )

    artifact_check_failed = any(
        item["severity"] == "BLOCKING"
        and (
            item["code"].startswith(("manifest.", "plot.output.", "technical.artifact."))
            or item["code"].startswith(
                ("plot.source.trace", "plot.source.artifact_trace")
            )
            or item["code"] == "scientific.data.artifact_trace_mismatch"
        )
        for item in issues
    )
    checks.extend(
        [
            {
                "id": "plot.data_binding",
                "status": "PASS" if binding.passed else "FAIL",
                "category": "Scientific",
                "message": "All plotted values resolve to declared authoritative data." if binding.passed else "Data Binding Gate reported blocking issues.",
            },
            {
                "id": "plot.source_reproducible",
                "status": "PASS" if plot_source_lint_passed(lint, strict=True) else "FAIL",
                "category": "Technical",
                "message": "Reproducible source is a thin hash-pinned PlotPlan runner.",
            },
            {
                "id": "plot.artifacts",
                "status": (
                    "PASS"
                    if not missing_formats
                    and manifest.get("status") == "COMPLETED"
                    and not artifact_check_failed
                    else "FAIL"
                ),
                "category": "Technical",
                "message": "Requested SVG/PDF/PNG artifacts and provenance were inspected.",
            },
            {
                "id": "plot.visual_review",
                "status": "SKIP",
                "category": "Visual",
                "message": "Human or vision-assisted visual review is not part of deterministic inspection.",
            },
        ]
    )
    summary = _summary(issues)
    outcome = (
        "BLOCKED"
        if summary["blocking"]
        else "REVISION_REQUIRED"
        if summary["major"] or summary["minor"]
        else "AUTOMATED_CHECKS_PASSED"
    )
    target = plan["target"]
    report = {
        "schema_version": "1.1",
        "run_id": f"{plan['plan_id']}-qa",
        "assessment_scope": "AUTOMATED_EXECUTION",
        "human_review_status": "NOT_PERFORMED",
        "outcome": outcome,
        "plan": _qa_ref(plan_path, qa_path.parent),
        "source": _qa_ref(source_path, qa_path.parent),
        "artifacts": [_qa_ref(path, qa_path.parent) for path in artifact_paths],
        "final_size": {
            "width": target["width"],
            "height": target["height"],
            "unit": target["unit"],
        },
        "summary": summary,
        "checks": checks,
        "issues": issues,
        "inspected_at": utc_now(),
        "metadata": {
            "backend": "matplotlib",
            "plot_plan_schema_version": plan["schema_version"],
            "manifest_schema_version": manifest.get("schema_version"),
            "data_binding_status": binding.trace["binding_status"],
            "authoritative_data_source_count": len(binding.datasets),
            "inspection_basis": "PlotPlan, data hashes, resolved execution trace, and artifact metadata",
            "ocr_used": False,
            "human_visual_review_required_for_full_pass": True,
        },
    }
    contract = validate_qa_contract(report)
    if contract:
        details = "; ".join(f"{item.code}: {item.message}" for item in contract)
        raise PlotInspectionError(f"Generated QA report violates QA 1.1: {details}")
    write_json_atomic(qa_path, report, overwrite=overwrite)
    return PlotInspectionResult(qa_path, report)


def format_inspection_result(result: PlotInspectionResult) -> str:
    report = result.report
    lines = [
        f"[{report['outcome']}] Matplotlib plot inspection",
        f"QA report: {result.qa_path}",
        f"Blocking: {report['summary']['blocking']}",
        f"Major: {report['summary']['major']}",
        f"Minor: {report['summary']['minor']}",
    ]
    lines.extend(f"[{item['severity']}] {item['code']}: {item['issue']}" for item in report["issues"])
    return "\n".join(lines)
