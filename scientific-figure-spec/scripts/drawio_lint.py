#!/usr/bin/env python3
"""Structural and geometry lint for uncompressed Draw.io mxGraph XML."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from figure_runtime import RuntimeIssue


@dataclass
class DrawioLintReport:
    path: Path
    issues: list[RuntimeIssue]
    cells: int = 0
    vertices: int = 0
    connectors: int = 0

    @property
    def errors(self) -> list[RuntimeIssue]:
        return [item for item in self.issues if item.severity == "ERROR"]

    @property
    def warnings(self) -> list[RuntimeIssue]:
        return [item for item in self.issues if item.severity == "WARNING"]

    def as_dict(self, *, strict: bool = False) -> dict[str, Any]:
        passed = not self.errors and (not strict or not self.warnings)
        return {
            "path": str(self.path),
            "passed": passed,
            "strict": strict,
            "summary": {
                "cells": self.cells,
                "vertices": self.vertices,
                "connectors": self.connectors,
                "errors": len(self.errors),
                "warnings": len(self.warnings),
            },
            "issues": [item.as_dict() for item in self.issues],
        }


def _style_map(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in (value or "").split(";"):
        token = token.strip()
        if not token or "=" not in token:
            continue
        key, item = token.split("=", 1)
        result[key.strip()] = item.strip()
    return result


def _float_attribute(
    geometry: ET.Element,
    attribute: str,
    *,
    cell_id: str,
    issues: list[RuntimeIssue],
) -> float | None:
    raw = geometry.get(attribute)
    if raw is None:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.geometry.missing_attribute",
                f"Cell {cell_id!r} geometry is missing {attribute!r}.",
                cell_id,
            )
        )
        return None
    try:
        value = float(raw)
    except ValueError:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.geometry.invalid",
                f"Cell {cell_id!r} has non-numeric {attribute}={raw!r}.",
                cell_id,
            )
        )
        return None
    if not math.isfinite(value):
        issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.geometry.invalid",
                f"Cell {cell_id!r} has non-finite {attribute}={raw!r}.",
                cell_id,
            )
        )
        return None
    return value


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    overlap_width = max(
        0.0,
        min(first_x + first_width, second_x + second_width) - max(first_x, second_x),
    )
    overlap_height = max(
        0.0,
        min(first_y + first_height, second_y + second_height) - max(first_y, second_y),
    )
    overlap = overlap_width * overlap_height
    smaller = min(first_width * first_height, second_width * second_height)
    return overlap / smaller if smaller > 0 else 0.0


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float = 1.0,
) -> bool:
    outer_x, outer_y, outer_width, outer_height = outer
    inner_x, inner_y, inner_width, inner_height = inner
    return (
        inner_x >= outer_x - tolerance
        and inner_y >= outer_y - tolerance
        and inner_x + inner_width <= outer_x + outer_width + tolerance
        and inner_y + inner_height <= outer_y + outer_height + tolerance
    )


def _unsafe_raster(cell: ET.Element, style: dict[str, str]) -> bool:
    raw_style = (cell.get("style") or "").casefold()
    value = (cell.get("value") or "").casefold()
    return (
        "image=" in raw_style
        or "shape=image" in raw_style
        or "data:image/" in raw_style
        or "<img" in value
        or "data:image/" in value
        or style.get("shape", "").casefold() == "image"
    )


def lint_drawio(path: Path) -> DrawioLintReport:
    path = path.expanduser().resolve()
    report = DrawioLintReport(path=path, issues=[])
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        report.issues.append(
            RuntimeIssue("ERROR", "drawio.file.missing", "Draw.io file does not exist.")
        )
        return report
    except OSError as exc:
        report.issues.append(
            RuntimeIssue("ERROR", "drawio.file.read", f"Could not read Draw.io file: {exc}")
        )
        return report

    upper_prefix = payload[:8192].upper()
    if b"<!DOCTYPE" in upper_prefix or b"<!ENTITY" in upper_prefix:
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.xml.unsafe_doctype",
                "DOCTYPE and ENTITY declarations are not allowed in Draw.io sources.",
            )
        )
        return report
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        report.issues.append(
            RuntimeIssue("ERROR", "drawio.xml.invalid", f"Invalid XML: {exc}")
        )
        return report

    if root.tag != "mxfile":
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.structure.mxfile_missing",
                f"Expected mxfile root, found {root.tag!r}.",
            )
        )
        return report

    diagrams = root.findall("diagram")
    if not diagrams:
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.structure.diagram_missing",
                "mxfile contains no diagram.",
            )
        )
        return report
    if len(diagrams) > 1:
        report.issues.append(
            RuntimeIssue(
                "WARNING",
                "drawio.structure.diagram_multiple",
                "The bundled inspector expects one page; additional diagrams will not be inspected.",
            )
        )

    diagram = diagrams[0]
    model = diagram.find("mxGraphModel")
    if root.get("compressed", "").casefold() == "true" or model is None:
        text = (diagram.text or "").strip()
        if text or root.get("compressed", "").casefold() == "true":
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.format.compressed",
                    "Draw.io source is compressed; the execution adapter requires editable uncompressed mxGraph XML.",
                )
            )
        if model is None:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.graph_model_missing",
                    "diagram does not contain an mxGraphModel element.",
                )
            )
            return report

    graph_root = model.find("root")
    if graph_root is None:
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.structure.root_missing",
                "mxGraphModel does not contain a root element.",
            )
        )
        return report

    try:
        page_width = float(model.get("pageWidth", ""))
        page_height = float(model.get("pageHeight", ""))
        if page_width <= 0 or page_height <= 0:
            raise ValueError
    except ValueError:
        page_width = page_height = 0.0
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "drawio.geometry.canvas_invalid",
                "mxGraphModel must define positive pageWidth and pageHeight.",
            )
        )

    cells = graph_root.findall("mxCell")
    report.cells = len(cells)
    id_to_cells: dict[str, list[ET.Element]] = {}
    for cell in cells:
        cell_id = cell.get("id")
        if not cell_id:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.id_missing",
                    "Every mxCell must have an ID.",
                )
            )
            continue
        id_to_cells.setdefault(cell_id, []).append(cell)
    for cell_id, matches in id_to_cells.items():
        if len(matches) > 1:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.id_duplicate",
                    f"mxCell ID is duplicated: {cell_id}",
                    cell_id,
                )
            )

    for base_id in ("0", "1"):
        if base_id not in id_to_cells:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.base_cell_missing",
                    f"Required Draw.io base cell {base_id!r} is missing.",
                    base_id,
                )
            )

    vertex_boxes: dict[str, tuple[float, float, float, float]] = {}
    vertex_styles: dict[str, dict[str, str]] = {}
    parent_by_id: dict[str, str | None] = {}
    vertices: set[str] = set()

    for cell in cells:
        cell_id = cell.get("id") or "(missing)"
        is_vertex = cell.get("vertex") == "1"
        is_edge = cell.get("edge") == "1"
        parent = cell.get("parent")
        parent_by_id[cell_id] = parent

        if cell_id not in {"0"} and parent is None:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.parent_missing",
                    f"Cell {cell_id!r} has no parent.",
                    cell_id,
                )
            )
        elif parent is not None and parent not in id_to_cells:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.parent_unknown",
                    f"Cell {cell_id!r} references unknown parent {parent!r}.",
                    cell_id,
                )
            )

        if cell_id in {"0", "1"}:
            continue
        if not is_vertex and not is_edge:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.cell_type_missing",
                    f"Cell {cell_id!r} is neither a vertex nor an edge.",
                    cell_id,
                )
            )
            continue

        style = _style_map(cell.get("style"))
        if _unsafe_raster(cell, style):
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.editability.embedded_raster",
                    f"Cell {cell_id!r} embeds or references raster imagery.",
                    cell_id,
                )
            )

        if is_vertex:
            report.vertices += 1
            vertices.add(cell_id)
            vertex_styles[cell_id] = style
            if not (cell.get("value") or "").strip():
                report.issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "drawio.text.empty_vertex",
                        f"Vertex {cell_id!r} has no text label.",
                        cell_id,
                    )
                )
            if (cell.get("value") or "").strip() and style.get("whiteSpace") != "wrap":
                report.issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "drawio.style.wrap_missing",
                        f"Vertex {cell_id!r} does not enable whiteSpace=wrap.",
                        cell_id,
                    )
                )
            geometry = cell.find("mxGeometry")
            if geometry is None:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.geometry.missing",
                        f"Vertex {cell_id!r} has no mxGeometry.",
                        cell_id,
                    )
                )
                continue
            values = [
                _float_attribute(
                    geometry,
                    attribute,
                    cell_id=cell_id,
                    issues=report.issues,
                )
                for attribute in ("x", "y", "width", "height")
            ]
            if any(value is None for value in values):
                continue
            x, y, width, height = (float(value) for value in values)
            if width <= 0 or height <= 0:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.geometry.nonpositive",
                        f"Vertex {cell_id!r} must have positive width and height.",
                        cell_id,
                    )
                )
                continue
            vertex_boxes[cell_id] = (x, y, width, height)

        if is_edge:
            report.connectors += 1
            source = cell.get("source")
            target = cell.get("target")
            for name, endpoint in (("source", source), ("target", target)):
                if not endpoint:
                    report.issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "drawio.connector.endpoint_missing",
                            f"Edge {cell_id!r} has no {name} endpoint.",
                            cell_id,
                        )
                    )
                elif endpoint not in id_to_cells:
                    report.issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "drawio.connector.endpoint_unknown",
                            f"Edge {cell_id!r} references unknown {name} {endpoint!r}.",
                            cell_id,
                        )
                    )
            geometry = cell.find("mxGeometry")
            if geometry is None:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.connector.geometry_missing",
                        f"Edge {cell_id!r} has no mxGeometry.",
                        cell_id,
                    )
                )
            elif geometry.get("relative") != "1":
                report.issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "drawio.connector.geometry_not_relative",
                        f"Edge {cell_id!r} should use relative=1 geometry.",
                        cell_id,
                    )
                )

    # Endpoint type checks run after every vertex has been collected.
    for cell in cells:
        if cell.get("edge") != "1":
            continue
        cell_id = cell.get("id") or "(missing)"
        for endpoint in (cell.get("source"), cell.get("target")):
            if endpoint in id_to_cells and endpoint not in vertices:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.connector.endpoint_type",
                        f"Edge {cell_id!r} endpoint {endpoint!r} is not a vertex.",
                        cell_id,
                    )
                )

    local_vertex_boxes = dict(vertex_boxes)
    absolute_vertex_boxes: dict[str, tuple[float, float, float, float]] = {}
    resolving: set[str] = set()

    def absolute_box(cell_id: str) -> tuple[float, float, float, float] | None:
        if cell_id in absolute_vertex_boxes:
            return absolute_vertex_boxes[cell_id]
        local = local_vertex_boxes.get(cell_id)
        if local is None:
            return None
        if cell_id in resolving:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.structure.parent_cycle",
                    f"Vertex parent hierarchy contains a cycle at {cell_id!r}.",
                    cell_id,
                )
            )
            return None
        resolving.add(cell_id)
        x, y, width, height = local
        parent = parent_by_id.get(cell_id)
        if parent in vertices:
            parent_local = local_vertex_boxes.get(parent)
            parent_absolute = absolute_box(parent)
            if vertex_styles.get(parent, {}).get("container") != "1":
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.structure.parent_not_container",
                        f"Vertex {cell_id!r} uses non-container parent {parent!r}.",
                        cell_id,
                    )
                )
            if parent_local is not None and not _contains(
                (0.0, 0.0, parent_local[2], parent_local[3]), local
            ):
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "drawio.geometry.child_out_of_parent",
                        f"Vertex {cell_id!r} extends outside parent {parent!r}.",
                        cell_id,
                    )
                )
            if parent_absolute is not None:
                x += parent_absolute[0]
                y += parent_absolute[1]
        resolving.discard(cell_id)
        result = (x, y, width, height)
        absolute_vertex_boxes[cell_id] = result
        return result

    for vertex_id in sorted(vertices):
        box = absolute_box(vertex_id)
        if box is None:
            continue
        x, y, width, height = box
        if page_width > 0 and page_height > 0 and (
            x < 0
            or y < 0
            or x + width > page_width
            or y + height > page_height
        ):
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "drawio.geometry.out_of_bounds",
                    f"Vertex {vertex_id!r} extends outside the {page_width:g}×{page_height:g} canvas.",
                    vertex_id,
                )
            )

    vertex_boxes = absolute_vertex_boxes

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        visited: set[str] = set()
        current = parent_by_id.get(descendant)
        while current in vertices and current not in visited:
            if current == ancestor:
                return True
            visited.add(current)
            current = parent_by_id.get(current)
        return False

    ids = sorted(vertex_boxes)
    for first_index, first_id in enumerate(ids):
        first_box = vertex_boxes[first_id]
        first_style = vertex_styles.get(first_id, {})
        for second_id in ids[first_index + 1 :]:
            second_box = vertex_boxes[second_id]
            second_style = vertex_styles.get(second_id, {})
            if is_ancestor(first_id, second_id) or is_ancestor(second_id, first_id):
                continue
            first_container = first_style.get("container") == "1"
            second_container = second_style.get("container") == "1"
            if first_container and _contains(first_box, second_box):
                continue
            if second_container and _contains(second_box, first_box):
                continue
            ratio = _overlap_ratio(first_box, second_box)
            if ratio >= 0.15:
                report.issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "drawio.geometry.overlap",
                        f"Vertices {first_id!r} and {second_id!r} overlap by {ratio:.0%} of the smaller area.",
                        f"{first_id},{second_id}",
                    )
                )
    return report


def lint_passed(report: DrawioLintReport, *, strict: bool = False) -> bool:
    return not report.errors and (not strict or not report.warnings)


def format_lint_report(report: DrawioLintReport, *, strict: bool = False) -> str:
    passed = lint_passed(report, strict=strict)
    lines = [f"[{'PASS' if passed else 'FAIL'}] {report.path}"]
    for issue in report.issues:
        location = f" ({issue.path})" if issue.path else ""
        lines.append(f"[{issue.severity}] {issue.code}{location}: {issue.message}")
    lines.extend(
        [
            "",
            "Summary",
            f"  Cells:      {report.cells}",
            f"  Vertices:   {report.vertices}",
            f"  Connectors: {report.connectors}",
            f"  Errors:     {len(report.errors)}",
            f"  Warnings:   {len(report.warnings)}",
        ]
    )
    return "\n".join(lines)
