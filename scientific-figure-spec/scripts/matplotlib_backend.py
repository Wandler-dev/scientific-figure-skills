#!/usr/bin/env python3
"""PlotPlan 1.0 authoring and Matplotlib execution adapter."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_utils import MEDIA_TYPES, file_reference, inspect_artifact_dimensions
from figure_runtime import (
    RuntimeContractError,
    RuntimeIssue,
    read_json,
    sha256_file,
    utc_now,
    validate_manifest_contract,
    validate_plot_plan_contract,
    write_json_atomic,
)
from plot_binding import BindingResult, validate_data_binding


SKILL_ROOT = Path(__file__).resolve().parent.parent
STYLE_ROOT = SKILL_ROOT / "assets" / "plot-styles"
GENERATED_MARKER = "scientific-figure-skills PlotPlan runner 1.0"
DEFAULT_COLORS = ["#2F6FB6", "#C56B2D", "#2C8A7D", "#7655A6", "#7A7A7A"]
DEFAULT_MARKERS = ["o", "s", "^", "D", "v", "P"]
DEFAULT_LINE_STYLES = ["-", "--", "-.", ":"]
DEFAULT_HATCHES = ["", "//", "\\\\", "xx", ".."]


class MatplotlibBackendError(RuntimeError):
    """Raised when a PlotPlan cannot be authored or rendered safely."""


@dataclass
class PlotSourceLintReport:
    source: Path
    issues: list[RuntimeIssue]

    def as_dict(self, *, strict: bool = False) -> dict[str, Any]:
        errors = sum(item.severity == "ERROR" for item in self.issues)
        warnings = sum(item.severity == "WARNING" for item in self.issues)
        return {
            "source": str(self.source),
            "errors": errors,
            "warnings": warnings,
            "strict": strict,
            "passed": errors == 0 and (not strict or warnings == 0),
            "issues": [item.as_dict() for item in self.issues],
        }


@dataclass
class MatplotlibExportResult:
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def success(self) -> bool:
        return self.manifest.get("status") == "COMPLETED"


def _write_text_atomic(path: Path, text: str, *, overwrite: bool) -> None:
    path = path.resolve()
    if path.exists() and not overwrite:
        raise MatplotlibBackendError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise MatplotlibBackendError(f"Could not write plot source {path}: {exc}") from exc


def _generated_source(plan_path: Path, expected_hash: str, source_path: Path) -> str:
    try:
        relative_plan = os.path.relpath(plan_path, source_path.parent)
    except ValueError:
        relative_plan = str(plan_path)
    return f'''#!/usr/bin/env python3
"""Reproducible runner generated from PlotPlan; scientific choices remain in JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from matplotlib_backend import execute_generated_source

GENERATED_BY = {GENERATED_MARKER!r}
EXPECTED_PLOT_PLAN_SHA256 = {expected_hash!r}
DEFAULT_PLOT_PLAN = (Path(__file__).resolve().parent / {relative_plan!r}).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce a scientific plot from PlotPlan 1.0.")
    parser.add_argument("--plot-plan", default=str(DEFAULT_PLOT_PLAN))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--format", dest="formats", action="append", choices=["svg", "pdf", "png"])
    args = parser.parse_args()
    result = execute_generated_source(
        Path(args.plot_plan),
        expected_plan_sha256=EXPECTED_PLOT_PLAN_SHA256,
        output_dir=Path(args.output_dir),
        trace_path=Path(args.trace),
        formats=args.formats,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def author_plot_source(
    plan_path: Path,
    output_path: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    plan_path = plan_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
    except RuntimeContractError as exc:
        raise MatplotlibBackendError(str(exc)) from exc
    issues = validate_plot_plan_contract(plan)
    errors = [item for item in issues if item.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{item.code}: {item.message}" for item in errors)
        raise MatplotlibBackendError(f"PlotPlan is invalid: {details}")
    if not isinstance(plan, dict) or plan.get("backend") != "matplotlib":
        raise MatplotlibBackendError("Matplotlib authoring requires PlotPlan backend='matplotlib'.")
    if output_path is None:
        output_path = plan_path.parent / plan["outputs"]["source"]
    output_path = output_path.expanduser()
    if not output_path.is_absolute():
        output_path = plan_path.parent / output_path
    output_path = output_path.resolve()
    if not output_path.name.endswith(".plot.py"):
        raise MatplotlibBackendError("Reproducible plot source must end with '.plot.py'.")
    _write_text_atomic(
        output_path,
        _generated_source(plan_path, sha256_file(plan_path), output_path),
        overwrite=overwrite,
    )
    try:
        output_path.chmod(output_path.stat().st_mode | 0o100)
    except OSError:
        pass
    return output_path


def lint_plot_source(source_path: Path, *, plan_path: Path | None = None) -> PlotSourceLintReport:
    source_path = source_path.expanduser().resolve()
    issues: list[RuntimeIssue] = []
    if not source_path.is_file():
        return PlotSourceLintReport(
            source_path,
            [RuntimeIssue("ERROR", "plot.source.missing", f"Plot source is not a regular file: {source_path}")],
        )
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return PlotSourceLintReport(
            source_path,
            [RuntimeIssue("ERROR", "plot.source.read_failed", f"Could not read plot source: {exc}")],
        )
    if GENERATED_MARKER not in text:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.source.runner_marker_missing",
                "Plot source is not the versioned thin PlotPlan runner.",
            )
        )
    match = re.search(r'^EXPECTED_PLOT_PLAN_SHA256\s*=\s*["\']([0-9a-f]{64})["\']', text, flags=re.M)
    if match is None:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.source.plan_hash_missing",
                "Plot source does not pin its PlotPlan hash.",
            )
        )
    elif plan_path is not None:
        resolved = plan_path.expanduser().resolve()
        if not resolved.is_file() or match.group(1) != sha256_file(resolved):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plot.source.plan_hash_mismatch",
                    "Plot source was generated for a different PlotPlan revision.",
                )
            )
        elif text != _generated_source(resolved, sha256_file(resolved), source_path):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plot.source.runner_drift",
                    "Plot source differs from the canonical thin runner for this PlotPlan.",
                )
            )
    forbidden = ("matplotlib.pyplot", ".plot(", ".bar(", ".scatter(", ".pcolormesh(")
    if any(token in text for token in forbidden):
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.source.scientific_config_present",
                "Generated source contains plotting decisions outside the PlotPlan backend.",
            )
        )
    return PlotSourceLintReport(source_path, issues)


def plot_source_lint_passed(report: PlotSourceLintReport, *, strict: bool = False) -> bool:
    return not any(
        item.severity == "ERROR" or (strict and item.severity == "WARNING")
        for item in report.issues
    )


def format_plot_lint_report(report: PlotSourceLintReport, *, strict: bool = False) -> str:
    payload = report.as_dict(strict=strict)
    lines = [
        f"[{'PASS' if payload['passed'] else 'FAIL'}] {report.source}",
        f"Errors: {payload['errors']}",
        f"Warnings: {payload['warnings']}",
    ]
    lines.extend(f"[{item.severity}] {item.code}: {item.message}" for item in report.issues)
    return "\n".join(lines)


def _style_path(profile: str) -> Path:
    path = STYLE_ROOT / f"{profile}.mplstyle"
    if not path.is_file():
        raise MatplotlibBackendError(f"Unknown or missing plot style profile: {profile}")
    return path


def _target_inches(target: dict[str, Any]) -> tuple[float, float]:
    width = float(target["width"])
    height = float(target["height"])
    if target["unit"] == "mm":
        return width / 25.4, height / 25.4
    return width, height


def _axis_label(axis: dict[str, Any]) -> str:
    unit = axis.get("unit")
    return f"{axis['label']} ({unit})" if unit else str(axis["label"])


def _series_style(series: dict[str, Any], index: int, profile: str) -> dict[str, Any]:
    specified = series.get("style") if isinstance(series.get("style"), dict) else {}
    grayscale = profile == "grayscale"
    return {
        "color": specified.get("color", "#333333" if grayscale else DEFAULT_COLORS[index % len(DEFAULT_COLORS)]),
        "marker": specified.get("marker", DEFAULT_MARKERS[index % len(DEFAULT_MARKERS)]),
        "linestyle": specified.get("line_style", DEFAULT_LINE_STYLES[index % len(DEFAULT_LINE_STYLES)]),
        "hatch": specified.get("hatch", DEFAULT_HATCHES[index % len(DEFAULT_HATCHES)]),
    }


def _finite_or_nan(values: list[Any]) -> list[float]:
    return [float(value) if isinstance(value, (int, float)) and math.isfinite(value) else math.nan for value in values]


def _apply_axes(ax: Any, panel: dict[str, Any]) -> None:
    axes = panel["axes"]
    ax.set_xlabel(_axis_label(axes["x"]))
    ax.set_ylabel(_axis_label(axes["y"]))
    ax.set_xscale(axes["x"]["scale"])
    ax.set_yscale(axes["y"]["scale"])
    if "limits" in axes["x"]:
        ax.set_xlim(*axes["x"]["limits"])
    if "limits" in axes["y"]:
        ax.set_ylim(*axes["y"]["limits"])
    if panel.get("title"):
        ax.set_title(panel["title"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#9AA7B2")


def _render_line_or_scatter(ax: Any, panel: dict[str, Any], resolved: dict[str, Any], profile: str) -> None:
    for index, series in enumerate(resolved["series"]):
        style = _series_style(series, index, profile)
        x_values = _finite_or_nan(series.get("x", []))
        y_values = _finite_or_nan(series.get("y", []))
        if panel["plot_type"] == "line":
            ax.plot(
                x_values,
                y_values,
                label=series.get("label"),
                color=style["color"],
                marker=style["marker"],
                linestyle=style["linestyle"],
            )
            if "lower" in series and "upper" in series:
                ax.fill_between(
                    x_values,
                    _finite_or_nan(series["lower"]),
                    _finite_or_nan(series["upper"]),
                    color=style["color"],
                    alpha=0.16,
                    linewidth=0,
                )
            elif "symmetric" in series:
                symmetric = _finite_or_nan(series["symmetric"])
                lower = [y - error for y, error in zip(y_values, symmetric, strict=True)]
                upper = [y + error for y, error in zip(y_values, symmetric, strict=True)]
                ax.fill_between(x_values, lower, upper, color=style["color"], alpha=0.16, linewidth=0)
        else:
            sizes = None
            size_column = panel.get("encoding", {}).get("size")
            if size_column and "size" in series:
                sizes = series["size"]
            ax.scatter(
                x_values,
                y_values,
                s=sizes,
                label=series.get("label"),
                color=style["color"],
                marker=style["marker"],
                edgecolors="white",
                linewidths=0.4,
            )


def _render_bar(ax: Any, panel: dict[str, Any], resolved: dict[str, Any], profile: str) -> None:
    series_items = resolved["series"]
    categories = list(panel.get("category_order") or [])
    if not categories:
        for series in series_items:
            for category in series.get("category", []):
                if category not in categories:
                    categories.append(category)
    width = 0.8 / max(1, len(series_items))
    centers = list(range(len(categories)))
    for index, series in enumerate(series_items):
        style = _series_style(series, index, profile)
        mapping = dict(zip(series.get("category", []), series.get("value", []), strict=True))
        values = [mapping.get(category, math.nan) for category in categories]
        positions = [center - 0.4 + width / 2 + index * width for center in centers]
        yerr = None
        if "symmetric" in series:
            uncertainty = dict(zip(series.get("category", []), series["symmetric"], strict=True))
            yerr = [uncertainty.get(category, math.nan) for category in categories]
        elif "lower" in series and "upper" in series:
            lower_map = dict(zip(series.get("category", []), series["lower"], strict=True))
            upper_map = dict(zip(series.get("category", []), series["upper"], strict=True))
            yerr = [
                [value - lower_map.get(category, value) for category, value in zip(categories, values, strict=True)],
                [upper_map.get(category, value) - value for category, value in zip(categories, values, strict=True)],
            ]
        ax.bar(
            positions,
            values,
            width=width,
            label=series.get("label"),
            color=style["color"],
            edgecolor="#333333",
            linewidth=0.5,
            hatch=style["hatch"],
            yerr=yerr,
            capsize=2 if yerr is not None else 0,
        )
    ax.set_xticks(centers, [str(item) for item in categories])


def _render_heatmap(fig: Any, ax: Any, panel: dict[str, Any], resolved: dict[str, Any]) -> None:
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize, TwoSlopeNorm
    from matplotlib.patches import Rectangle

    x_categories: list[str] = []
    y_categories: list[str] = []
    for cell in resolved["cells"]:
        if cell["x"] not in x_categories:
            x_categories.append(cell["x"])
        if cell["y"] not in y_categories:
            y_categories.append(cell["y"])
    color_scale = panel["color_scale"]
    values = [float(cell["value"]) for cell in resolved["cells"]]
    if color_scale["kind"] == "diverging":
        center = float(color_scale["center"])
        spread = max((abs(value - center) for value in values), default=1.0) or 1.0
        norm = TwoSlopeNorm(vmin=center - spread, vcenter=center, vmax=center + spread)
    else:
        minimum = min(values)
        maximum = max(values)
        if minimum == maximum:
            padding = max(1.0, abs(minimum) * 0.01)
            minimum -= padding
            maximum += padding
        norm = Normalize(vmin=minimum, vmax=maximum)
    colormap = fig.get_cmap(color_scale["cmap"]) if hasattr(fig, "get_cmap") else None
    if colormap is None:
        from matplotlib import colormaps

        colormap = colormaps[color_scale["cmap"]]
    for cell in resolved["cells"]:
        x_index = x_categories.index(cell["x"])
        y_index = y_categories.index(cell["y"])
        ax.add_patch(
            Rectangle(
                (x_index - 0.5, y_index - 0.5),
                1.0,
                1.0,
                facecolor=colormap(norm(float(cell["value"]))),
                edgecolor="white",
                linewidth=0.6,
            )
        )
    ax.set_xlim(-0.5, len(x_categories) - 0.5)
    ax.set_ylim(len(y_categories) - 0.5, -0.5)
    ax.set_xticks(range(len(x_categories)), x_categories)
    ax.set_yticks(range(len(y_categories)), y_categories)
    colorbar = fig.colorbar(ScalarMappable(norm=norm, cmap=colormap), ax=ax, fraction=0.05, pad=0.04)
    if colorbar.solids is not None:
        colorbar.solids.set_rasterized(False)
    label = color_scale.get("label", panel["axes"]["y"]["label"])
    if color_scale.get("unit"):
        label = f"{label} ({color_scale['unit']})"
    colorbar.set_label(label)


def _apply_annotations_and_references(ax: Any, panel: dict[str, Any]) -> None:
    for reference in panel.get("reference_lines", []):
        options = {"color": "#5E6B75", "linestyle": "--", "linewidth": 0.9}
        if reference["axis"] == "x":
            ax.axvline(reference["value"], label=reference.get("label"), **options)
        else:
            ax.axhline(reference["value"], label=reference.get("label"), **options)
    for annotation in panel.get("annotations", []):
        if "x" in annotation and "y" in annotation:
            ax.annotate(annotation["text"], (annotation["x"], annotation["y"]), xytext=(4, 4), textcoords="offset points")
        else:
            ax.text(0.02, 0.98, annotation["text"], transform=ax.transAxes, va="top", ha="left")


def _render_bound_plot(
    binding: BindingResult,
    *,
    output_dir: Path,
    formats: list[str],
) -> tuple[list[Path], dict[str, Any]]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties, findfont
    except ImportError as exc:
        raise MatplotlibBackendError("capability.matplotlib.missing: Matplotlib is not installed.") from exc

    plan = binding.plan
    style_path = _style_path(plan["style_profile"])
    width, height = _target_inches(plan["target"])
    output_dir.mkdir(parents=True, exist_ok=True)
    with matplotlib.rc_context(fname=style_path):
        matplotlib.rcParams["svg.hashsalt"] = str(plan["plan_id"])
        figure = Figure(figsize=(width, height), dpi=plan["target"]["dpi"], constrained_layout=True)
        FigureCanvasAgg(figure)
        layout = plan["layout"]
        grid = figure.add_gridspec(
            layout["rows"],
            layout["columns"],
            hspace=layout.get("vertical_space", 0.25),
            wspace=layout.get("horizontal_space", 0.25),
        )
        axes_by_panel: dict[str, Any] = {}
        for panel, resolved in zip(plan["panels"], binding.resolved_panels, strict=True):
            placement = panel["grid"]
            row = placement["row"]
            column = placement["column"]
            rowspan = placement.get("rowspan", 1)
            colspan = placement.get("colspan", 1)
            ax = figure.add_subplot(grid[row : row + rowspan, column : column + colspan])
            axes_by_panel[panel["id"]] = ax
            # Configure scales before categorical renderers install their fixed
            # locators. Matplotlib resets locators when set_xscale() is called,
            # so applying axes afterward would replace bar/heatmap labels with
            # numeric ticks.
            _apply_axes(ax, panel)
            if panel["plot_type"] in {"line", "scatter"}:
                _render_line_or_scatter(ax, panel, resolved, plan["style_profile"])
            elif panel["plot_type"] == "bar":
                _render_bar(ax, panel, resolved, plan["style_profile"])
            else:
                _render_heatmap(figure, ax, panel, resolved)
            _apply_annotations_and_references(ax, panel)
            if panel["legend"]["mode"] == "panel":
                ax.legend(
                    title=panel["legend"].get("title"),
                    loc=panel["legend"].get("location", "best"),
                    frameon=False,
                )
        if layout["shared_legend"]:
            handles: list[Any] = []
            labels: list[str] = []
            figure_legend_ids = {
                panel["id"]
                for panel in plan["panels"]
                if panel.get("legend", {}).get("mode") == "figure"
            }
            for panel_id, ax in axes_by_panel.items():
                if panel_id not in figure_legend_ids:
                    continue
                axis_handles, axis_labels = ax.get_legend_handles_labels()
                for handle, label in zip(axis_handles, axis_labels, strict=True):
                    if label and label not in labels:
                        handles.append(handle)
                        labels.append(label)
            if handles:
                figure.legend(
                    handles,
                    labels,
                    loc="upper center",
                    bbox_to_anchor=(0.5, 1.0),
                    ncol=max(1, len(labels)),
                    frameon=False,
                )

        source_base = plan["outputs"]["source"][: -len(".plot.py")]
        artifacts: list[Path] = []
        for format_name in formats:
            output = output_dir / f"{source_base}.{format_name}"
            metadata: dict[str, Any] | None
            if format_name == "svg":
                metadata = {"Date": None, "Creator": "scientific-figure-skills"}
            elif format_name == "pdf":
                metadata = {"CreationDate": None, "ModDate": None, "Creator": "scientific-figure-skills"}
            else:
                metadata = {"Software": "scientific-figure-skills"}
            figure.savefig(output, format=format_name, dpi=plan["target"]["dpi"], metadata=metadata)
            artifacts.append(output)
        requested_fonts = list(matplotlib.rcParams.get("font.sans-serif", []))
        resolved_font_path = findfont(
            FontProperties(family=matplotlib.rcParams.get("font.family", ["sans-serif"])),
            fallback_to_default=True,
        )
        resolved_font_name = FontProperties(fname=resolved_font_path).get_name()
        execution = {
            **binding.trace,
            "binding_status": "COMPLETE",
            "style_profile": plan["style_profile"],
            "target": plan["target"],
            "formats": formats,
            "matplotlib_version": matplotlib.__version__,
            "python_version": sys.version.split()[0],
            "font_resolution": {
                "requested": requested_fonts,
                "resolved_name": resolved_font_name,
                "resolved_path": resolved_font_path,
                "fallback_used": bool(requested_fonts) and resolved_font_name.casefold()
                not in {str(item).casefold() for item in requested_fonts},
            },
            "minimum_configured_text_size_pt": min(
                float(matplotlib.rcParams[key])
                for key in ("font.size", "axes.labelsize", "axes.titlesize", "xtick.labelsize", "ytick.labelsize", "legend.fontsize")
                if isinstance(matplotlib.rcParams[key], (int, float))
            ),
            "artifact_outputs": [
                {
                    "format": format_name,
                    "sha256": sha256_file(output),
                    "size_bytes": output.stat().st_size,
                    "dimensions": inspect_artifact_dimensions(output, format_name),
                }
                for format_name, output in zip(formats, artifacts, strict=True)
            ],
        }
        return artifacts, execution


def execute_generated_source(
    plan_path: Path,
    *,
    expected_plan_sha256: str,
    output_dir: Path,
    trace_path: Path,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    if not plan_path.is_file() or sha256_file(plan_path) != expected_plan_sha256:
        return {
            "success": False,
            "issues": [
                {
                    "severity": "ERROR",
                    "code": "plot.source.plan_hash_mismatch",
                    "message": "Generated source does not match the current PlotPlan hash.",
                }
            ],
        }
    try:
        plan_value = read_json(plan_path)
        if not isinstance(plan_value, dict):
            raise MatplotlibBackendError("PlotPlan must be a JSON object.")
        requested = formats or list(plan_value["outputs"]["formats"])
        if not requested or any(item not in {"svg", "pdf", "png"} for item in requested):
            raise MatplotlibBackendError("Requested plot formats must be a non-empty SVG/PDF/PNG subset.")
        binding = validate_data_binding(plan_path, plan=plan_value)
        if not binding.passed:
            return {"success": False, "issues": [item.as_dict() for item in binding.issues]}
        artifacts, trace = _render_bound_plot(binding, output_dir=output_dir.resolve(), formats=requested)
        write_json_atomic(trace_path.resolve(), trace, overwrite=True)
        return {
            "success": True,
            "artifacts": [str(path.resolve()) for path in artifacts],
            "trace": str(trace_path.resolve()),
            "issues": [item.as_dict() for item in binding.issues],
        }
    except (RuntimeContractError, MatplotlibBackendError, KeyError, TypeError, ValueError, OSError) as exc:
        return {
            "success": False,
            "issues": [
                {
                    "severity": "ERROR",
                    "code": "plot.export.failed",
                    "message": str(exc),
                }
            ],
        }


def _manifest_issue(issue: RuntimeIssue | dict[str, Any]) -> dict[str, str]:
    if isinstance(issue, RuntimeIssue):
        return {"severity": issue.severity, "code": issue.code, "message": issue.message}
    return {
        "severity": str(issue.get("severity", "ERROR")),
        "code": str(issue.get("code", "plot.export.failed")),
        "message": str(issue.get("message", "Plot export failed.")),
    }


def _write_manifest(path: Path, manifest: dict[str, Any], *, overwrite: bool) -> None:
    issues = validate_manifest_contract(manifest)
    if issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in issues)
        raise MatplotlibBackendError(f"Refusing to write invalid artifact manifest: {details}")
    write_json_atomic(path, manifest, overwrite=overwrite)


def export_matplotlib(
    *,
    plan_path: Path,
    source_path: Path,
    output_dir: Path | None = None,
    formats: list[str] | None = None,
    manifest_path: Path | None = None,
    overwrite: bool = False,
    strict_lint: bool = False,
    timeout_seconds: int = 60,
) -> MatplotlibExportResult:
    plan_path = plan_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
    except RuntimeContractError as exc:
        raise MatplotlibBackendError(str(exc)) from exc
    if not isinstance(plan, dict):
        raise MatplotlibBackendError("PlotPlan must be a JSON object.")
    plan_issues = validate_plot_plan_contract(plan)
    errors = [item for item in plan_issues if item.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{item.code}: {item.message}" for item in errors)
        raise MatplotlibBackendError(f"PlotPlan is invalid: {details}")
    if plan.get("backend") != "matplotlib":
        raise MatplotlibBackendError("Matplotlib exporter received a non-Matplotlib PlotPlan.")
    if importlib.util.find_spec("matplotlib") is None:
        raise MatplotlibBackendError(
            "capability.matplotlib.missing: Matplotlib is an optional runtime and is not installed."
        )
    if not source_path.is_file():
        raise MatplotlibBackendError(f"Reproducible plot source is not a regular file: {source_path}")

    output_dir = output_dir.expanduser().resolve() if output_dir else plan_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path is None:
        manifest_path = plan_path.parent / plan["outputs"]["manifest"]
    manifest_path = manifest_path.expanduser()
    if not manifest_path.is_absolute():
        manifest_path = output_dir / manifest_path
    manifest_path = manifest_path.resolve()
    if manifest_path.exists() and not overwrite:
        raise MatplotlibBackendError(f"Refusing to overwrite existing manifest: {manifest_path}")

    requested = formats or list(plan["outputs"]["formats"])
    if not requested or any(item not in {"svg", "pdf", "png"} for item in requested):
        raise MatplotlibBackendError("Requested formats must be a non-empty SVG/PDF/PNG subset.")
    requested = list(dict.fromkeys(requested))
    source_base = plan["outputs"]["source"][: -len(".plot.py")]
    targets = {item: output_dir / f"{source_base}.{item}" for item in requested}
    trace_path = manifest_path.parent / plan["outputs"]["trace"]
    collisions = [path for path in [*targets.values(), trace_path] if path.exists() and not overwrite]
    if collisions:
        raise MatplotlibBackendError(f"Refusing to overwrite existing outputs: {collisions}")

    lint_report = lint_plot_source(source_path, plan_path=plan_path)
    binding = validate_data_binding(plan_path, plan=plan)
    issues: list[RuntimeIssue | dict[str, Any]] = [*lint_report.issues, *binding.issues]
    base = manifest_path.parent
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": f"{plan['plan_id']}-export",
        "status": "BLOCKED",
        "plan": file_reference(plan_path, base, "application/json"),
        "source": file_reference(source_path, base, "text/x-python"),
        "exporter": {
            "backend": "matplotlib",
            "command": [],
            "version": None,
            "exit_code": None,
        },
        "artifacts": [],
        "issues": [],
        "created_at": utc_now(),
        "metadata": {
            "python_version": sys.version.split()[0],
            "inputs": [
                {
                    "id": data.source_id,
                    "format": data.format,
                    "role": "authoritative_plot_data",
                    **file_reference(
                        data.path,
                        base,
                        "text/csv"
                        if data.format == "csv"
                        else "text/tab-separated-values"
                        if data.format == "tsv"
                        else "application/json",
                    ),
                }
                for data in binding.datasets.values()
            ],
            "resolved_trace": None,
            "target": plan["target"],
            "style_profile": plan["style_profile"],
        },
    }
    blocking = any(
        (item.severity if isinstance(item, RuntimeIssue) else item.get("severity")) == "ERROR"
        for item in issues
    )
    if strict_lint and any(item.severity == "WARNING" for item in lint_report.issues):
        blocking = True
    if blocking:
        manifest["issues"] = [_manifest_issue(item) for item in issues]
        _write_manifest(manifest_path, manifest, overwrite=overwrite)
        return MatplotlibExportResult(manifest_path, manifest)

    with tempfile.TemporaryDirectory(prefix="scientific-plot-export-") as tmp:
        temporary_root = Path(tmp)
        temporary_output = temporary_root / "artifacts"
        temporary_trace = temporary_root / "trace.json"
        command = [
            sys.executable,
            str(source_path),
            "--plot-plan",
            str(plan_path),
            "--output-dir",
            str(temporary_output),
            "--trace",
            str(temporary_trace),
        ]
        for format_name in requested:
            command.extend(["--format", format_name])
        environment = os.environ.copy()
        scripts_path = str(Path(__file__).resolve().parent)
        environment["PYTHONPATH"] = scripts_path + (
            os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
        environment["MPLCONFIGDIR"] = str(temporary_root / "mplconfig")
        environment.setdefault("SOURCE_DATE_EPOCH", "0")
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            completed = None
            issues.append(
                RuntimeIssue("ERROR", "plot.export.process_failed", f"Could not execute plot source: {exc}")
            )
        payload: dict[str, Any] = {}
        if completed is not None:
            manifest["exporter"]["command"] = command
            manifest["exporter"]["exit_code"] = completed.returncode
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plot.export.output_invalid",
                        "Reproducible plot source did not emit valid JSON execution output.",
                    )
                )
            if completed.returncode != 0 or not payload.get("success"):
                for item in payload.get("issues", []):
                    issues.append(item)
                if not payload.get("issues"):
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plot.export.process_failed",
                            completed.stderr.strip() or "Matplotlib execution failed.",
                        )
                    )
        if completed is not None and completed.returncode == 0 and payload.get("success"):
            trace = read_json(temporary_trace)
            matplotlib_version = trace.get("matplotlib_version") if isinstance(trace, dict) else None
            manifest["exporter"]["version"] = matplotlib_version
            font_resolution = trace.get("font_resolution") if isinstance(trace, dict) else None
            manifest["metadata"]["font_resolution"] = font_resolution
            if isinstance(font_resolution, dict) and font_resolution.get("fallback_used") is True:
                issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "plot.style.font_fallback",
                        f"Matplotlib resolved {font_resolution.get('resolved_name')!r} instead of a requested font family.",
                    )
                )
            for format_name, target in targets.items():
                source = temporary_output / f"{source_base}.{format_name}"
                if not source.is_file() or source.stat().st_size == 0:
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plot.export.artifact_missing",
                            f"Matplotlib did not create a non-empty {format_name.upper()} artifact.",
                        )
                    )
                    continue
                dimensions = inspect_artifact_dimensions(source, format_name)
                if dimensions is None:
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plot.export.artifact_invalid",
                            f"Generated {format_name.upper()} artifact failed format/dimension validation.",
                        )
                    )
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                record = file_reference(target, base, MEDIA_TYPES[format_name])
                record["format"] = format_name
                record["dimensions"] = dimensions
                manifest["artifacts"].append(record)
            if not any(
                (item.severity if isinstance(item, RuntimeIssue) else item.get("severity")) == "ERROR"
                for item in issues
            ):
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temporary_trace, trace_path)
                manifest["metadata"]["resolved_trace"] = file_reference(
                    trace_path, base, "application/json"
                )

    errors_present = any(
        (item.severity if isinstance(item, RuntimeIssue) else item.get("severity")) == "ERROR"
        for item in issues
    )
    manifest["status"] = "FAILED" if errors_present else "COMPLETED"
    manifest["issues"] = [_manifest_issue(item) for item in issues]
    _write_manifest(manifest_path, manifest, overwrite=overwrite)
    return MatplotlibExportResult(manifest_path, manifest)


def format_export_result(result: MatplotlibExportResult) -> str:
    lines = [
        f"Status: {result.manifest['status']}",
        f"Manifest: {result.manifest_path}",
    ]
    for artifact in result.manifest.get("artifacts", []):
        lines.append(f"Artifact: {artifact['format']} {artifact['path']} ({artifact['size_bytes']} bytes)")
    for issue in result.manifest.get("issues", []):
        lines.append(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
    return "\n".join(lines)
