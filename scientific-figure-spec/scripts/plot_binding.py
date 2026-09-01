#!/usr/bin/env python3
"""Data Binding Gate for PlotPlan 1.0.

The gate proves that planned visual values resolve to declared local data. It
does not perform statistical analysis, imputation, smoothing, or inference.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import validate_figure_spec as figure_spec_validator
from figure_coverage import normalized_requirement_text
from figure_runtime import (
    RuntimeContractError,
    RuntimeIssue,
    read_json,
    sha256_file,
    validate_plot_plan_contract,
)
from plot_data import (
    LoadedData,
    filtered_rows,
    is_missing,
    load_data_source,
    numeric_value,
    resolve_declared_path,
    value_digest,
)
from plot_plan import SECTION_REQUIREMENTS, extract_plot_requirements


@dataclass
class BindingResult:
    plan_path: Path
    plan: dict[str, Any]
    figure_spec_path: Path | None
    datasets: dict[str, LoadedData]
    resolved_panels: list[dict[str, Any]]
    trace: dict[str, Any]
    issues: list[RuntimeIssue]

    @property
    def passed(self) -> bool:
        return not any(item.severity == "ERROR" for item in self.issues)


class PlotBindingError(RuntimeError):
    """Raised when binding setup cannot be read safely."""


def _issue(
    issues: list[RuntimeIssue],
    code: str,
    message: str,
    path: str | None = None,
    *,
    severity: str = "ERROR",
) -> None:
    issues.append(RuntimeIssue(severity, code, message, path))


def _known_columns(
    data: LoadedData,
    columns: Iterable[str],
    *,
    issues: list[RuntimeIssue],
    path: str,
) -> bool:
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        _issue(
            issues,
            "plot.binding.column_missing",
            f"Data source {data.source_id!r} is missing bound columns: {missing}.",
            path,
        )
        return False
    return True


def _coverage_is_complete(
    plan: dict[str, Any],
    requirements: dict[str, list[str]],
    issues: list[RuntimeIssue],
) -> bool:
    coverage = plan.get("spec_coverage")
    if not isinstance(coverage, dict):
        _issue(
            issues,
            "scientific.coverage.missing",
            "PlotPlan has no spec_coverage gate.",
            "$.spec_coverage",
        )
        return False
    complete = coverage.get("status") == "COMPLETE"
    for section, expected_values in requirements.items():
        recorded = coverage.get(section)
        if not isinstance(recorded, list):
            _issue(
                issues,
                "scientific.coverage.section_missing",
                f"PlotPlan coverage is missing {section!r}.",
                f"$.spec_coverage.{section}",
            )
            complete = False
            continue
        expected = sorted(normalized_requirement_text(item) for item in expected_values)
        actual = sorted(
            normalized_requirement_text(str(item.get("source_text", "")))
            for item in recorded
            if isinstance(item, dict)
        )
        if actual != expected:
            _issue(
                issues,
                "scientific.coverage.source_mismatch",
                f"PlotPlan {section} coverage does not exactly match the current FigureSpec.",
                f"$.spec_coverage.{section}",
            )
            complete = False
        for item in recorded:
            if isinstance(item, dict) and item.get("status") != "MAPPED":
                _issue(
                    issues,
                    f"scientific.coverage.{section}_unmapped",
                    f"Unresolved FigureSpec requirement: {item.get('source_ref')}: {item.get('source_text')}",
                    f"$.spec_coverage.{section}",
                )
                complete = False
    return complete


def _filter_valid(
    filter_spec: dict[str, Any] | None,
    data: LoadedData,
    *,
    issues: list[RuntimeIssue],
    path: str,
) -> bool:
    if filter_spec is None:
        return True
    column = filter_spec.get("column")
    if not isinstance(column, str) or column not in data.columns:
        _issue(
            issues,
            "plot.binding.filter_column_missing",
            f"Filter references unknown column {column!r} in {data.source_id!r}.",
            path,
        )
        return False
    operator = filter_spec.get("operator")
    if operator == "eq" and "value" not in filter_spec:
        _issue(
            issues,
            "plot.binding.filter_value_missing",
            "An eq filter requires value.",
            path,
        )
        return False
    if operator == "in" and not isinstance(filter_spec.get("values"), list):
        _issue(
            issues,
            "plot.binding.filter_values_missing",
            "An in filter requires values[].",
            path,
        )
        return False
    return True


def _prepare_rows(
    rows: list[dict[str, Any]],
    required_columns: list[str],
    *,
    missing_policy: str,
    plot_type: str,
    gap_column: str | None,
    gap_related_columns: set[str],
    issues: list[RuntimeIssue],
    path: str,
) -> tuple[list[dict[str, Any]], int, int]:
    kept: list[dict[str, Any]] = []
    missing_count = 0
    omitted_count = 0
    for row_index, row in enumerate(rows, start=1):
        missing = [column for column in required_columns if is_missing(row.get(column))]
        if not missing:
            kept.append(row)
            continue
        missing_count += 1
        if missing_policy == "drop":
            omitted_count += 1
            continue
        if (
            missing_policy == "gap"
            and plot_type == "line"
            and gap_column is not None
            and gap_column in missing
            and set(missing).issubset(gap_related_columns)
        ):
            kept.append(row)
            continue
        _issue(
            issues,
            "plot.binding.missing_value",
            f"Row {row_index} has missing plot-required values in {missing}; policy is {missing_policy!r}.",
            path,
        )
    return kept, missing_count, omitted_count


def _number(
    value: Any,
    *,
    issues: list[RuntimeIssue],
    path: str,
    allow_missing: bool = False,
) -> float | None:
    if is_missing(value) and allow_missing:
        return None
    try:
        return numeric_value(value)
    except ValueError as exc:
        _issue(issues, "plot.data.numeric_invalid", str(exc), path)
        return None


def _category(
    value: Any,
    *,
    issues: list[RuntimeIssue],
    path: str,
) -> str | int | float | None:
    if (
        is_missing(value)
        or isinstance(value, bool)
        or not isinstance(value, (str, int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        _issue(
            issues,
            "plot.data.categorical_invalid",
            f"{value!r} is not a usable scalar categorical value.",
            path,
        )
        return None
    return value


def _axis_values(
    plot_type: str,
    resolved: dict[str, Any],
    axis_name: str,
) -> list[float]:
    result: list[float] = []
    for series in resolved.get("series", []):
        if plot_type in {"line", "scatter"}:
            key = axis_name
        elif plot_type == "bar":
            key = "value" if axis_name == "y" else ""
        else:
            key = "value" if axis_name == "z" else ""
        for value in series.get(key, []) if key else []:
            if isinstance(value, (int, float)) and math.isfinite(value):
                result.append(float(value))
        if axis_name == "y":
            for key in ("lower", "upper"):
                for value in series.get(key, []):
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        result.append(float(value))
            base_key = "value" if plot_type == "bar" else "y"
            base_values = series.get(base_key, [])
            symmetric = series.get("symmetric", [])
            if isinstance(base_values, list) and isinstance(symmetric, list):
                for base, error in zip(base_values, symmetric, strict=False):
                    if (
                        isinstance(base, (int, float))
                        and math.isfinite(base)
                        and isinstance(error, (int, float))
                        and math.isfinite(error)
                    ):
                        result.extend((float(base - error), float(base + error)))
    if plot_type == "heatmap" and axis_name == "z":
        for value in resolved.get("values", []):
            if isinstance(value, (int, float)) and math.isfinite(value):
                result.append(float(value))
    return result


def _validate_axis(
    panel: dict[str, Any],
    resolved: dict[str, Any],
    axis_name: str,
    values: list[float],
    *,
    issues: list[RuntimeIssue],
    path: str,
) -> None:
    axis = panel.get("axes", {}).get(axis_name, {})
    if not isinstance(axis, dict):
        return
    if axis.get("scale") == "log" and any(value <= 0 for value in values):
        _issue(
            issues,
            "plot.axis.log_nonpositive",
            f"Panel {panel.get('id')!r} {axis_name}-axis is log-scaled but bound data include zero or negative values.",
            path,
        )
    limits = axis.get("limits")
    if isinstance(limits, list) and len(limits) == 2 and values:
        clipped = [value for value in values if value < limits[0] or value > limits[1]]
        if clipped and axis.get("allow_clipping") is not True:
            _issue(
                issues,
                "plot.axis.data_clipped",
                f"Panel {panel.get('id')!r} {axis_name}-axis limits exclude {len(clipped)} bound data or uncertainty values.",
                path,
            )


def _resolve_series_panel(
    panel: dict[str, Any],
    datasets: dict[str, LoadedData],
    *,
    issues: list[RuntimeIssue],
    panel_index: int,
) -> dict[str, Any]:
    panel_id = str(panel.get("id"))
    panel_path = f"$.panels[{panel_index}]"
    plot_type = str(panel.get("plot_type"))
    encoding = panel.get("encoding") if isinstance(panel.get("encoding"), dict) else {}
    missing_policy = str(panel.get("missing_policy"))
    resolved: dict[str, Any] = {
        "panel_id": panel_id,
        "plot_type": plot_type,
        "data_source_id": panel.get("data_source"),
        "encoding": dict(encoding),
        "missing_policy": missing_policy,
        "series": [],
        "omitted_count": 0,
        "missing_count": 0,
    }

    series_items = panel.get("series") if isinstance(panel.get("series"), list) else []
    for series_index, series in enumerate(series_items):
        if not isinstance(series, dict):
            continue
        series_id = str(series.get("id"))
        series_path = f"{panel_path}.series[{series_index}]"
        source_id = series.get("data_source", panel.get("data_source"))
        data = datasets.get(source_id) if isinstance(source_id, str) else None
        if data is None:
            _issue(
                issues,
                "plot.binding.data_source_unresolved",
                f"Series {series_id!r} cannot resolve data source {source_id!r}.",
                series_path,
            )
            continue
        filter_spec = series.get("filter")
        if filter_spec is not None and not isinstance(filter_spec, dict):
            filter_spec = None
        if not _filter_valid(filter_spec, data, issues=issues, path=f"{series_path}.filter"):
            continue
        rows = filtered_rows(data, filter_spec)
        if not rows:
            _issue(
                issues,
                "plot.series.empty",
                f"Series {series_id!r} resolves to zero rows.",
                series_path,
            )
            continue

        if plot_type in {"line", "scatter"}:
            columns = [encoding.get("x"), encoding.get("y")]
            output_keys: tuple[str, ...] = ("x", "y")
            if plot_type == "scatter" and isinstance(encoding.get("size"), str):
                columns.append(encoding["size"])
                output_keys = ("x", "y", "size")
        elif plot_type == "bar":
            columns = [encoding.get("category"), encoding.get("value")]
            output_keys = ("category", "value")
        else:
            columns = []
            output_keys = ()
        required_columns = [item for item in columns if isinstance(item, str)]
        uncertainty = panel.get("uncertainty")
        uncertainty_columns: list[str] = []
        if isinstance(uncertainty, dict):
            uncertainty_columns = [
                value
                for key in ("lower_column", "upper_column", "symmetric_column")
                if isinstance((value := uncertainty.get(key)), str)
            ]
        all_columns = [*required_columns, *uncertainty_columns]
        group_column = encoding.get("group")
        if isinstance(group_column, str):
            all_columns.append(group_column)
        filter_column = filter_spec.get("column") if isinstance(filter_spec, dict) else None
        if isinstance(filter_column, str):
            all_columns.append(filter_column)
        if not _known_columns(data, all_columns, issues=issues, path=series_path):
            continue

        gap_column = encoding.get("y") if plot_type == "line" else None
        gap_related_columns = (
            {str(encoding.get("y")), *uncertainty_columns}
            if plot_type == "line" and isinstance(encoding.get("y"), str)
            else set()
        )
        prepared, missing_count, omitted_count = _prepare_rows(
            rows,
            all_columns,
            missing_policy=missing_policy,
            plot_type=plot_type,
            gap_column=gap_column if isinstance(gap_column, str) else None,
            gap_related_columns=gap_related_columns,
            issues=issues,
            path=series_path,
        )
        if not prepared:
            _issue(
                issues,
                "plot.series.empty_after_missing",
                f"Series {series_id!r} has no rows after applying missing_policy={missing_policy!r}.",
                series_path,
            )
        if panel.get("sort_by"):
            sort_column = panel["sort_by"]
            if sort_column not in data.columns:
                _issue(
                    issues,
                    "plot.binding.sort_column_missing",
                    f"sort_by references unknown column {sort_column!r}.",
                    panel_path,
                )
            else:
                def key(row: dict[str, Any]) -> tuple[int, Any]:
                    value = row.get(sort_column)
                    if is_missing(value):
                        return (1, "")
                    try:
                        return (0, numeric_value(value))
                    except ValueError:
                        return (0, str(value))

                prepared = sorted(prepared, key=key)

        if isinstance(group_column, str):
            for row_index, row in enumerate(prepared):
                _category(
                    row.get(group_column),
                    issues=issues,
                    path=f"{series_path}.{group_column}[{row_index}]",
                )

        output: dict[str, Any] = {
            "series_id": series_id,
            "label": series.get("label"),
            "data_source_id": source_id,
            "filter": filter_spec,
            "row_count": len(prepared),
            "missing_count": missing_count,
            "omitted_count": omitted_count,
            "style": {
                key: series[key]
                for key in ("color", "marker", "line_style", "hatch")
                if key in series
            },
        }
        for column, key_name in zip(required_columns, output_keys, strict=True):
            values: list[Any] = []
            for row_index, row in enumerate(prepared):
                value = row.get(column)
                numeric = key_name in {"x", "y", "value", "size"} and not (
                    plot_type == "bar" and key_name == "category"
                )
                if numeric:
                    values.append(
                        _number(
                            value,
                            issues=issues,
                            path=f"{series_path}.{column}[{row_index}]",
                            allow_missing=missing_policy == "gap" and key_name == "y",
                        )
                    )
                else:
                    values.append(
                        _category(
                            value,
                            issues=issues,
                            path=f"{series_path}.{column}[{row_index}]",
                        )
                    )
            output[key_name] = values

        if isinstance(uncertainty, dict):
            if "symmetric_column" in uncertainty:
                symmetric = []
                for row_index, row in enumerate(prepared):
                    gap_row = missing_policy == "gap" and is_missing(row.get(encoding.get("y")))
                    value = None if gap_row else _number(
                        row.get(uncertainty["symmetric_column"]),
                        issues=issues,
                        path=f"{series_path}.uncertainty[{row_index}]",
                    )
                    symmetric.append(value)
                output["symmetric"] = symmetric
                output["uncertainty_kind"] = uncertainty.get("kind")
            else:
                for key_name, column_key in (
                    ("lower", "lower_column"),
                    ("upper", "upper_column"),
                ):
                    values = []
                    column = uncertainty.get(column_key)
                    for row_index, row in enumerate(prepared):
                        gap_row = missing_policy == "gap" and is_missing(row.get(encoding.get("y")))
                        values.append(
                            None if gap_row else _number(
                                row.get(column),
                                issues=issues,
                                path=f"{series_path}.{column}[{row_index}]",
                            )
                        )
                    output[key_name] = values
                output["uncertainty_kind"] = uncertainty.get("kind")

        if "symmetric" in output:
            if any(
                isinstance(value, (int, float)) and value < 0
                for value in output["symmetric"]
            ):
                _issue(
                    issues,
                    "plot.uncertainty.negative",
                    f"Series {series_id!r} contains negative symmetric uncertainty.",
                    series_path,
                )
        central_key = "value" if plot_type == "bar" else "y"
        if all(key in output for key in (central_key, "lower", "upper")):
            for row_index, (value, lower, upper) in enumerate(
                zip(output[central_key], output["lower"], output["upper"], strict=True)
            ):
                if None in {value, lower, upper}:
                    continue
                if not (lower <= value <= upper):
                    _issue(
                        issues,
                        "plot.uncertainty.bounds_invalid",
                        f"Series {series_id!r} row {row_index + 1} is not bracketed by lower/upper uncertainty bounds.",
                        series_path,
                    )

        if plot_type == "scatter" and any(
            isinstance(value, (int, float)) and value <= 0
            for value in output.get("size", [])
        ):
            _issue(
                issues,
                "plot.series.size_nonpositive",
                f"Scatter series {series_id!r} contains a non-positive marker size.",
                series_path,
            )

        if plot_type == "bar":
            categories = output.get("category", [])
            if len(categories) != len({str(item) for item in categories}):
                _issue(
                    issues,
                    "plot.binding.category_duplicate",
                    f"Bar series {series_id!r} resolves more than one value for the same category.",
                    series_path,
                )

        digest_payload = {
            key: output.get(key)
            for key in ("x", "y", "category", "value", "lower", "upper", "symmetric")
            if key in output
        }
        output["data_digest"] = value_digest(digest_payload)
        resolved["series"].append(output)
        resolved["missing_count"] += missing_count
        resolved["omitted_count"] += omitted_count

    if plot_type == "bar" and panel.get("category_order"):
        declared = list(panel["category_order"])
        actual: list[Any] = []
        for series in resolved["series"]:
            for category in series.get("category", []):
                if category not in actual:
                    actual.append(category)
            series_categories = list(series.get("category", []))
            if set(declared) != set(series_categories):
                _issue(
                    issues,
                    "plot.binding.category_missing",
                    f"Series {series.get('series_id')!r} categories {series_categories!r} do not match category_order {declared!r}.",
                    panel_path,
                )
        if set(declared) != set(actual):
            _issue(
                issues,
                "plot.binding.category_missing",
                f"Explicit category_order {declared!r} does not exactly match bound categories {actual!r}.",
                panel_path,
            )

    _validate_axis(
        panel,
        resolved,
        "x",
        _axis_values(plot_type, resolved, "x"),
        issues=issues,
        path=f"{panel_path}.axes.x",
    )
    _validate_axis(
        panel,
        resolved,
        "y",
        _axis_values(plot_type, resolved, "y"),
        issues=issues,
        path=f"{panel_path}.axes.y",
    )
    return resolved


def _resolve_heatmap_panel(
    panel: dict[str, Any],
    datasets: dict[str, LoadedData],
    *,
    issues: list[RuntimeIssue],
    panel_index: int,
) -> dict[str, Any]:
    panel_path = f"$.panels[{panel_index}]"
    source_id = panel.get("data_source")
    data = datasets.get(source_id) if isinstance(source_id, str) else None
    encoding = panel.get("encoding") if isinstance(panel.get("encoding"), dict) else {}
    resolved: dict[str, Any] = {
        "panel_id": panel.get("id"),
        "plot_type": "heatmap",
        "data_source_id": source_id,
        "encoding": dict(encoding),
        "missing_policy": panel.get("missing_policy"),
        "series": [],
        "cells": [],
        "values": [],
        "missing_count": 0,
        "omitted_count": 0,
    }
    if data is None:
        _issue(
            issues,
            "plot.binding.data_source_unresolved",
            f"Heatmap panel cannot resolve data source {source_id!r}.",
            panel_path,
        )
        return resolved
    columns = [encoding.get("x"), encoding.get("y"), encoding.get("value")]
    required = [item for item in columns if isinstance(item, str)]
    if not _known_columns(data, required, issues=issues, path=panel_path):
        return resolved
    prepared, missing_count, omitted_count = _prepare_rows(
        list(data.rows),
        required,
        missing_policy=str(panel.get("missing_policy")),
        plot_type="heatmap",
        gap_column=None,
        gap_related_columns=set(),
        issues=issues,
        path=panel_path,
    )
    seen_cells: set[tuple[str, str]] = set()
    for row_index, row in enumerate(prepared):
        raw_x = _category(
            row.get(encoding.get("x")),
            issues=issues,
            path=f"{panel_path}.x[{row_index}]",
        )
        raw_y = _category(
            row.get(encoding.get("y")),
            issues=issues,
            path=f"{panel_path}.y[{row_index}]",
        )
        if raw_x is None or raw_y is None:
            continue
        x_value = str(raw_x)
        y_value = str(raw_y)
        key = (x_value, y_value)
        if key in seen_cells:
            _issue(
                issues,
                "plot.binding.heatmap_cell_duplicate",
                f"Heatmap cell {key!r} is declared more than once.",
                panel_path,
            )
            continue
        seen_cells.add(key)
        value = _number(
            row.get(encoding.get("value")),
            issues=issues,
            path=f"{panel_path}.value[{row_index}]",
        )
        resolved["cells"].append({"x": x_value, "y": y_value, "value": value})
        resolved["values"].append(value)
    resolved["missing_count"] = missing_count
    resolved["omitted_count"] = omitted_count
    resolved["data_digest"] = value_digest(resolved["cells"])
    x_categories = {cell["x"] for cell in resolved["cells"]}
    y_categories = {cell["y"] for cell in resolved["cells"]}
    missing_cells = len(x_categories) * len(y_categories) - len(resolved["cells"])
    resolved["missing_cell_count"] = missing_cells
    if missing_cells and panel.get("missing_policy") == "error":
        _issue(
            issues,
            "plot.binding.heatmap_cell_missing",
            f"Heatmap panel {panel.get('id')!r} is missing {missing_cells} x/y category cell(s) under missing_policy='error'.",
            panel_path,
        )
    if not resolved["cells"]:
        _issue(
            issues,
            "plot.panel.empty",
            f"Heatmap panel {panel.get('id')!r} resolves to no cells.",
            panel_path,
        )
    return resolved


def _validate_bound_source(
    source: dict[str, Any],
    declared_value: Any,
    datasets: dict[str, LoadedData],
    *,
    issues: list[RuntimeIssue],
    path: str,
) -> None:
    source_id = source.get("data_source")
    column = source.get("column")
    data = datasets.get(source_id) if isinstance(source_id, str) else None
    if data is None or not isinstance(column, str) or column not in data.columns:
        _issue(
            issues,
            "scientific.data.unbound_value",
            "Scientific annotation/reference value cannot resolve its declared data source and column.",
            path,
        )
        return
    filter_spec = source.get("filter")
    if filter_spec is not None and not isinstance(filter_spec, dict):
        filter_spec = None
    if not _filter_valid(filter_spec, data, issues=issues, path=path):
        return
    rows = filtered_rows(data, filter_spec)
    values = [row.get(column) for row in rows if not is_missing(row.get(column))]
    if not values:
        _issue(
            issues,
            "scientific.data.unbound_value",
            "Scientific annotation/reference binding resolves to no authoritative value.",
            path,
        )
        return
    def equivalent(value: Any, declared: Any) -> bool:
        if value == declared or str(value) == str(declared):
            return True
        try:
            return math.isclose(
                numeric_value(value),
                numeric_value(declared),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        except ValueError:
            return False

    if declared_value is not None and not any(
        equivalent(value, declared_value) for value in values
    ):
        _issue(
            issues,
            "scientific.data.unbound_value",
            f"Declared scientific value {declared_value!r} is absent from its authoritative binding.",
            path,
        )


def _text_represents_bound_value(text: str, value: Any) -> bool:
    normalized_text = " ".join(text.split()).casefold()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
            try:
                if math.isclose(float(token), float(value), rel_tol=1e-12, abs_tol=1e-12):
                    return True
            except ValueError:
                continue
        return False
    token = str(value).strip().casefold()
    return bool(token) and re.search(
        rf"(?<!\w){re.escape(token)}(?!\w)", normalized_text
    ) is not None


def _finite_range(values: Any) -> dict[str, float] | None:
    if not isinstance(values, list):
        return None
    finite = [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ]
    return {"min": min(finite), "max": max(finite)} if finite else None


def validate_data_binding(
    plan_path: Path,
    *,
    plan: dict[str, Any] | None = None,
) -> BindingResult:
    plan_path = plan_path.expanduser().resolve()
    if plan is None:
        try:
            value = read_json(plan_path)
        except RuntimeContractError as exc:
            raise PlotBindingError(str(exc)) from exc
        if not isinstance(value, dict):
            raise PlotBindingError("PlotPlan must be a JSON object.")
        plan = value
    issues = list(validate_plot_plan_contract(plan))
    datasets: dict[str, LoadedData] = {}
    resolved_panels: list[dict[str, Any]] = []

    figure_spec_path: Path | None = None
    figure_spec = plan.get("figure_spec")
    requirements = {key: [] for key in SECTION_REQUIREMENTS}
    if isinstance(figure_spec, dict) and isinstance(figure_spec.get("path"), str):
        figure_spec_path = resolve_declared_path(figure_spec["path"], plan_path)
        if not figure_spec_path.is_file():
            _issue(
                issues,
                "plot.plan.figure_spec_missing",
                f"Referenced FigureSpec is not a regular file: {figure_spec_path}",
                "$.figure_spec.path",
            )
        else:
            if sha256_file(figure_spec_path) != figure_spec.get("sha256"):
                _issue(
                    issues,
                    "plot.plan.figure_spec_hash_mismatch",
                    "FigureSpec changed after PlotPlan creation; regenerate or deliberately update the PlotPlan.",
                    "$.figure_spec.sha256",
                )
            text = figure_spec_path.read_text(encoding="utf-8")
            metadata, error = figure_spec_validator.extract_frontmatter(text)
            if error or not isinstance(metadata, dict):
                _issue(
                    issues,
                    "plot.plan.figure_spec_invalid",
                    error or "Referenced FigureSpec has invalid frontmatter.",
                    "$.figure_spec",
                )
            else:
                if metadata.get("figure_id") != plan.get("figure_id"):
                    _issue(
                        issues,
                        "plot.plan.figure_id_mismatch",
                        "Current FigureSpec identity does not match PlotPlan figure_id.",
                        "$.figure_spec.figure_id",
                    )
                requirements = extract_plot_requirements(figure_spec_path)
                _coverage_is_complete(plan, requirements, issues)

    declarations = plan.get("data_sources")
    for declaration in declarations if isinstance(declarations, list) else []:
        if not isinstance(declaration, dict):
            continue
        loaded, load_issues = load_data_source(declaration, plan_path)
        issues.extend(load_issues)
        if loaded is not None:
            datasets[loaded.source_id] = loaded

    panels = plan.get("panels")
    if isinstance(panels, list) and not panels:
        _issue(
            issues,
            "plot.panel.missing",
            "A PlotPlan scaffold needs at least one explicit panel before rendering.",
            "$.panels",
        )
    for panel_index, panel in enumerate(panels if isinstance(panels, list) else []):
        if not isinstance(panel, dict):
            continue
        if panel.get("plot_type") == "heatmap":
            resolved = _resolve_heatmap_panel(
                panel,
                datasets,
                issues=issues,
                panel_index=panel_index,
            )
        else:
            resolved = _resolve_series_panel(
                panel,
                datasets,
                issues=issues,
                panel_index=panel_index,
            )
        resolved_panels.append(resolved)

        for annotation_index, annotation in enumerate(panel.get("annotations", [])):
            if not isinstance(annotation, dict) or not isinstance(annotation.get("source"), dict):
                continue
            source = annotation["source"]
            source_type = source.get("type")
            if source_type in {"data_column", "source_bound_constant"}:
                declared_value = source.get("value", annotation.get("text"))
                _validate_bound_source(
                    source,
                    declared_value,
                    datasets,
                    issues=issues,
                    path=f"$.panels[{panel_index}].annotations[{annotation_index}]",
                )
                if "value" in source and not _text_represents_bound_value(
                    str(annotation.get("text", "")), source["value"]
                ):
                    _issue(
                        issues,
                        "scientific.data.unbound_value",
                        f"Annotation text {annotation.get('text')!r} does not represent its declared source-bound value {source['value']!r}.",
                        f"$.panels[{panel_index}].annotations[{annotation_index}]",
                    )
            elif source_type == "figure_spec_label":
                expected_labels = {
                    normalized_requirement_text(item).removesuffix(".")
                    for item in requirements.get("required_labels", [])
                }
                annotation_text = normalized_requirement_text(
                    str(annotation.get("text", ""))
                ).removesuffix(".")
                if annotation_text not in expected_labels:
                    _issue(
                        issues,
                        "scientific.data.unbound_value",
                        f"Annotation text {annotation.get('text')!r} is not declared in FigureSpec Required Figure Labels.",
                        f"$.panels[{panel_index}].annotations[{annotation_index}]",
                    )
        for reference_index, reference in enumerate(panel.get("reference_lines", [])):
            if not isinstance(reference, dict) or reference.get("source_type") != "source_bound_constant":
                continue
            source = reference.get("source")
            if not isinstance(source, dict):
                _issue(
                    issues,
                    "scientific.data.unbound_value",
                    "Source-bound reference line has no data source binding.",
                    f"$.panels[{panel_index}].reference_lines[{reference_index}]",
                )
                continue
            _validate_bound_source(
                source,
                reference.get("value"),
                datasets,
                issues=issues,
                path=f"$.panels[{panel_index}].reference_lines[{reference_index}]",
            )

    trace_panels: list[dict[str, Any]] = []
    panel_by_id = {
        panel.get("id"): panel
        for panel in panels if isinstance(panels, list) and isinstance(panel, dict)
    }
    for resolved in resolved_panels:
        declared_panel = panel_by_id.get(resolved.get("panel_id"), {})
        encoding = resolved.get("encoding", {})
        columns = {
            key: encoding[key]
            for key in ("x", "y", "category", "value", "group", "size")
            if isinstance(encoding, dict) and key in encoding
        }
        uncertainty = declared_panel.get("uncertainty") if isinstance(declared_panel, dict) else None
        uncertainty_columns = {
            key: uncertainty[key]
            for key in ("lower_column", "upper_column", "symmetric_column")
            if isinstance(uncertainty, dict) and key in uncertainty
        }
        panel_trace = {
            key: resolved.get(key)
            for key in (
                "panel_id",
                "plot_type",
                "data_source_id",
                "encoding",
                "missing_policy",
                "missing_count",
                "missing_cell_count",
                "omitted_count",
                "data_digest",
            )
            if key in resolved
        }
        panel_trace["bound_columns"] = columns
        panel_trace["uncertainty_columns"] = uncertainty_columns
        if resolved.get("plot_type") == "heatmap":
            panel_trace["resolved_cell_count"] = len(resolved.get("cells", []))
            panel_trace["value_range"] = _finite_range(resolved.get("values", []))
        panel_trace["series"] = [
            {
                **{
                    key: series.get(key)
                    for key in (
                        "series_id",
                        "label",
                        "data_source_id",
                        "filter",
                        "row_count",
                        "missing_count",
                        "omitted_count",
                        "uncertainty_kind",
                        "data_digest",
                    )
                    if key in series
                },
                "value_ranges": {
                    key: range_value
                    for key in ("x", "y", "value", "size", "lower", "upper", "symmetric")
                    if (range_value := _finite_range(series.get(key))) is not None
                },
            }
            for series in resolved.get("series", [])
        ]
        trace_panels.append(panel_trace)

    trace = {
        "schema_version": "1.0",
        "plan_id": plan.get("plan_id"),
        "plot_plan_sha256": sha256_file(plan_path) if plan_path.is_file() else None,
        "figure_spec_sha256": sha256_file(figure_spec_path) if figure_spec_path and figure_spec_path.is_file() else None,
        "binding_status": "BLOCKED" if any(item.severity == "ERROR" for item in issues) else "COMPLETE",
        "data_sources": [
            {
                "id": source.source_id,
                "path": str(source.path),
                "sha256": source.sha256,
                "row_count": source.row_count,
                "columns": list(source.columns),
            }
            for source in datasets.values()
        ],
        "panels": trace_panels,
    }
    return BindingResult(
        plan_path=plan_path,
        plan=plan,
        figure_spec_path=figure_spec_path,
        datasets=datasets,
        resolved_panels=resolved_panels,
        trace=trace,
        issues=issues,
    )


def format_binding_result(result: BindingResult) -> str:
    label = "PASS" if result.passed else "BLOCKED"
    lines = [
        f"[{label}] PlotPlan data binding",
        f"Data sources: {len(result.datasets)}",
        f"Panels: {len(result.resolved_panels)}",
    ]
    for issue in result.issues:
        location = f" ({issue.path})" if issue.path else ""
        lines.append(f"[{issue.severity}] {issue.code}{location}: {issue.message}")
    return "\n".join(lines)
